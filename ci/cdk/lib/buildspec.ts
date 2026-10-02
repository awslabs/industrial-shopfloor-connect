// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as codebuild from 'aws-cdk-lib/aws-codebuild';

/**
 * The buildspec for the SFC integration-test project.
 *
 * Several things here look arbitrary and are not. Each was verified against this repository:
 *
 * - `GRADLE_OPTS` must NOT contain `--no-daemon`. `gradlew` splices `$GRADLE_OPTS` into the **JVM**
 *   argument list ahead of `GradleWrapperMain`, so a Gradle CLI flag there kills the wrapper outright.
 *   The daemon is disabled with `-Dorg.gradle.daemon=false` instead.
 * - `org.gradle.parallel`, `org.gradle.caching` and the configuration cache are passed on the command
 *   line rather than written into `gradle.properties`, because this work does not modify product files.
 *   They matter: without them a 39-module build recompiles everything serially on every push.
 * - The top-level `cache.paths` block is mandatory. `codebuild.Cache.bucket()` only says *where* the
 *   cache lives; if the buildspec declares no paths, nothing is ever archived and every build is cold.
 * - `clean` is never invoked. The root build wires `clean` to `finalizedBy("cleanAll")`, which deletes
 *   the entire root `build/` directory - including `build/distribution`, which the tests read.
 * - Evidence is uploaded per phase, not only in `post_build`. `post_build` does **not** run when a build
 *   is `TIMED_OUT` or stopped, which is exactly when the logs are most wanted.
 * - `sfc-uberjar -h` is not used as a smoke test: `-h` never reaches the help handler on the sfc-main
 *   path and exits 1.
 */
export interface BuildspecProps {
  /** Bucket for evidence, reports and the Gradle cache. */
  readonly artifactsBucket: string;
  /** Deployment modes to exercise, in order. */
  readonly modes: string[];
  /** Tiers to run: `core`, `aws`, or both. */
  readonly tiers: string[];
}

export function buildSpec(props: BuildspecProps): codebuild.BuildSpec {
  const modes = props.modes.join(',');
  const tiers = props.tiers.join(',');

  return codebuild.BuildSpec.fromObject({
    version: '0.2',
    env: {
      variables: {
        // JVM options only - see the note above about --no-daemon.
        GRADLE_OPTS: '-Dorg.gradle.daemon=false',
        GRADLE_USER_HOME: '/codebuild/gradle',
        SFC_E2E_MODES: modes,
        SFC_E2E_TIERS: tiers,
        // Keeps every case's output out of the container's default temp dir so the artifact upload has
        // one predictable root.
        SFC_E2E_OUT: '/codebuild/e2e-out',
      },
    },
    phases: {
      install: {
        'runtime-versions': {
          // The product targets bytecode 17 (milo 1.1.7 requires it) and the Gradle toolchain resolves
          // 17 regardless, but matching the container JDK avoids a toolchain download on every build.
          java: 'corretto17',
          python: '3.12',
        },
        commands: [
          'set -euo pipefail',
          'java -version',
          'python3 --version',
          // Kafka in-container stands in for MSK: it exercises the target's write path and the
          // aws-msk-iam-auth wiring with no VPC, no cluster-creation wait and no standing cost.
          // Skipped unless the AWS tier is selected.
          'if [ "${SFC_E2E_TIERS}" != "core" ]; then ci/scripts/install-kafka.sh; fi',
        ],
      },
      pre_build: {
        commands: [
          'set -euo pipefail',
          'mkdir -p "$SFC_E2E_OUT"',
          // Provenance for the report. The source arrives as an S3 zip, so CODEBUILD_RESOLVED_SOURCE_VERSION
          // is not a commit; the launcher passes the real values in as environment overrides.
          'export SFC_E2E_COMMIT="${SFC_E2E_COMMIT:-unknown}"',
          'export SFC_E2E_REF="${SFC_E2E_REF:-unknown}"',
          // Deliberately NOT `clean` - see the header note.
          './gradlew --parallel --build-cache --configuration-cache build',
          'ls -l build/distribution/*.tar.gz | head -5',
          'test "$(ls build/distribution/*.tar.gz | wc -l)" -ge 38',
          './gradlew --parallel --build-cache :tests:e2e-support:build',
          'if [ "${SFC_E2E_TIERS}" != "core" ]; then python3 ci/scripts/provision.py; fi',
        ],
      },
      build: {
        commands: [
          'set -euo pipefail',
          // CodeBuild phases do not share shell state, so provision.py writes its exports to a file
          // rather than exporting them. Without this the SFC_E2E_* placeholders in the AWS-tier configs
          // are unset, and SFC aborts with "Placeholder ... could not be replaced" - loudly, which is
          // the intended failure mode, but for the wrong reason.
          'if [ -f /codebuild/e2e-env.sh ]; then . /codebuild/e2e-env.sh; fi',
          // The suite's own exit status is the build's verdict. `|| true` would hide it, so the status is
          // captured and re-raised after the report has been produced and uploaded.
          'set +e',
          'python3 tests/e2e/run.py --tier "$SFC_E2E_TIERS" --modes "$SFC_E2E_MODES" --parity --out "$SFC_E2E_OUT"',
          'E2E_STATUS=$?',
          'set -e',
          // Uploaded here, in the same phase, so a later timeout cannot lose it.
          `aws s3 cp --recursive "$SFC_E2E_OUT" "s3://${props.artifactsBucket}/evidence/\${CODEBUILD_BUILD_ID##*:}/" --only-show-errors || true`,
          'echo "e2e exit status: $E2E_STATUS"',
          'exit $E2E_STATUS',
        ],
      },
      post_build: {
        commands: [
          // Best-effort only. The authoritative teardown is the EventBridge-driven janitor, because this
          // phase is skipped entirely on TIMED_OUT and on a stopped build.
          'set +e',
          'if [ -f /codebuild/e2e-env.sh ]; then . /codebuild/e2e-env.sh; fi',
          'if [ "${SFC_E2E_TIERS}" != "core" ]; then python3 ci/scripts/cleanup.py; fi',
          `aws s3 cp --recursive "$SFC_E2E_OUT" "s3://${props.artifactsBucket}/evidence/\${CODEBUILD_BUILD_ID##*:}/" --only-show-errors`,
        ],
      },
    },
    reports: {
      // Surfaces per-case pass/fail in the CodeBuild console. The build role needs
      // codebuild:CreateReportGroup / CreateReport / UpdateReport / BatchPutTestCases for this to work.
      'sfc-e2e': {
        files: ['junit.xml'],
        'base-directory': '/codebuild/e2e-out/**',
        'file-format': 'JUNITXML',
        'discard-paths': 'yes',
      },
    },
    artifacts: {
      'base-directory': '/codebuild/e2e-out',
      files: ['**/*'],
    },
    cache: {
      // Without this block the project-level S3 cache archives nothing at all.
      // build-cache-1 is included deliberately: it is what makes an unchanged module skip recompilation,
      // which is the single biggest win available on a 39-module build.
      paths: [
        '/codebuild/gradle/caches/modules-2/**/*',
        '/codebuild/gradle/caches/build-cache-1/**/*',
        '/codebuild/gradle/caches/jars-*/**/*',
        '/codebuild/gradle/wrapper/dists/**/*',
        '/opt/kafka/**/*',
      ],
    },
  });
}
