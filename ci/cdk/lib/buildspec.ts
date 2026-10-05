// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as codebuild from 'aws-cdk-lib/aws-codebuild';

/**
 * The buildspec for the SFC integration-test project.
 *
 * Choices here that look arbitrary are not; each was verified against this repository:
 *
 * - `GRADLE_OPTS` carries JVM options only. `gradlew` splices it into the **JVM** argument list, so a Gradle
 *   flag such as `--no-daemon` there kills the wrapper.
 * - `--parallel --build-cache` are passed on the command line, not written into gradle.properties: this
 *   work does not change product files. `--configuration-cache` is absent on purpose - settings.gradle.kts
 *   runs `git describe` at configuration time and Gradle fails the build with "external process started".
 * - The top-level `cache.paths` block is mandatory. `Cache.bucket()` only says where the cache lives.
 * - `clean` is never run: it is wired to `cleanAll`, which deletes build/distribution, the suite's input.
 * - Evidence is uploaded per case by the runner itself. `post_build` is skipped on TIMED_OUT and on a stopped
 *   build - exactly when the evidence is wanted most.
 * - It runs on the suite's own image (ci/cdk/image/Dockerfile, built by the image project), which has the
 *   JDK, Python with the harness's packages and every counterpart preinstalled. CodeBuild's
 *   `runtime-versions` only exists on its curated images, so there is none here.
 */
export interface BuildspecProps {
  readonly artifactsBucket: string;
  readonly reportGroupArn: string;
}

export function buildSpec(props: BuildspecProps): codebuild.BuildSpec {
  return codebuild.BuildSpec.fromObject({
    version: '0.2',
    env: {
      // CodeBuild's default shell is /bin/sh (dash on Ubuntu), which has no 'set -o pipefail'.
      shell: 'bash',
      variables: {
        GRADLE_OPTS: '-Dorg.gradle.daemon=false',
        GRADLE_USER_HOME: '/codebuild/gradle',
        SFC_E2E_PROFILE: 'push',
        SFC_E2E_JOBS: '8',
        KAFKA_HOME: '/opt/kafka',
      },
    },
    phases: {
      install: {
        // Everything is preinstalled in the build image (ci/cdk/image/Dockerfile). The pip step only adds
        // what the tree under test needs beyond the image; it is a no-op when nothing changed.
        commands: [
          'set -euo pipefail',
          'java -version && python3 --version && mosquitto -h | head -1 && nats-server --version',
          'pip3 install --quiet -r ci/e2e/requirements.txt',
        ],
      },
      pre_build: {
        commands: [
          'set -euo pipefail',
          'mkdir -p e2e-out',
          // The source is an S3 zip; the executable bit is not guaranteed to survive.
          'chmod +x gradlew',
          './gradlew --parallel --build-cache build',
          'test "$(ls build/distribution/*.tar.gz | wc -l)" -ge 38',
          'python3 -m unittest discover -s ci/e2e/selftest',
          // Stale per-case topics from builds that died before their own cleanup, swept over the public
          // IAM endpoint at the start of every build.
          'python3 ci/e2e/lib/kafka_admin.py sweep --older-than 7200 || echo "kafka sweep skipped"',
        ],
      },
      build: {
        commands: [
          'set -euo pipefail',
          // The suite's exit status is the build's verdict; capture it, upload, then re-raise.
          'set +e',
          'python3 ci/e2e/run.py --profile "$SFC_E2E_PROFILE" ${SFC_E2E_TIERS:+--tier "$SFC_E2E_TIERS"} ${SFC_E2E_MODES:+--modes "$SFC_E2E_MODES"} --jobs "$SFC_E2E_JOBS" --parity --out e2e-out --evidence "s3://' + props.artifactsBucket + '/evidence/${CODEBUILD_BUILD_ID##*:}/"',
          'E2E_STATUS=$?',
          'set -e',
          'echo "e2e exit status: $E2E_STATUS"',
          'exit $E2E_STATUS',
        ],
      },
      post_build: {
        commands: [
          // Best effort; the runner has already uploaded each case as it finished.
          'aws s3 cp --recursive e2e-out "s3://' + props.artifactsBucket + '/evidence/${CODEBUILD_BUILD_ID##*:}/" --exclude "artifacts/*" --only-show-errors || true',
        ],
      },
    },
    reports: {
      [props.reportGroupArn]: {
        files: ['**/junit.xml'],
        'base-directory': 'e2e-out',
        'file-format': 'JUNITXML',
      },
    },
    cache: {
      paths: [
        '/codebuild/gradle/caches/modules-2/**/*',
        '/codebuild/gradle/caches/build-cache-1/**/*',
        '/codebuild/gradle/caches/jars-*/**/*',
        '/codebuild/gradle/wrapper/dists/**/*',
      ],
    },
  });
}
