# SFC end-to-end tests

Runs the **real SFC process** against declarative test cases in all three deployment modes — in-process,
IPC and uberjar — and produces a markdown report.

Before this suite the repository had 97 test files and every one of them was a transformation-operator
unit test. There were no tests for filters, aggregation, metadata, schedules, config parsing, templates or
chaining, and no tests at all in any of the 15 adapter or 19 target modules.

## Running it

Requires a JVM and a prior `./gradlew build` — the suite runs against the released tarballs, not the
Gradle class directories, because the packaging is part of what is under test.

```shell
./gradlew build                      # produces build/distribution/*.tar.gz
./gradlew :tests:e2e-support:build   # the local metrics writer the assertions read

tests/e2e/run.py --tier core --mode inprocess
tests/e2e/run.py --tier core --modes inprocess,ipc,uberjar --parity
tests/e2e/run.py --case CORE-XFRM-LOG2-01 --mode uberjar
tests/e2e/run.py --list
```

The **core tier needs no AWS account, no credentials and no network.** That is verified by running it with
every AWS environment variable unset.

Output lands in `tests/e2e/out/<run-id>/`: `REPORT.md`, `results.json`, `junit.xml`, and a directory per
case holding its rendered config, logs, sink data and metrics.

## The three modes

Each case has **one** `config.json`, written in canonical form: components named by `FactoryClassName`
alone, no `JarFiles`, no server keys. `lib/modes.py` derives all three concrete configurations from it. If
each mode had its own hand-written config, a parity failure could always be dismissed as "the configs
differ" — this way it cannot.

| Mode | How it runs | What only this mode covers |
|---|---|---|
| `inprocess` | `sfc-main/bin/sfc-main` with `JarFiles` pointing at unpacked module `lib/` dirs | the `URLClassLoader` branch of `InstanceFactory`, and the real per-module classpath |
| `ipc` | each adapter and target as its own gRPC service on a runner-allocated port, then `sfc-main` | gRPC serialisation both ways; the only mode whose processes install shutdown hooks |
| `uberjar` | `java -cp sfc-uberjar-<v>.jar com.amazonaws.sfc.MainController` | the merged fat jar: `Class.forName` on the system classpath, one `log4j2.xml`, merged service files |

`--parity` asserts the output is byte-identical across modes after normalising serials and timestamps.
That is the single most valuable assertion here, because a component behaving differently depending on how
it was loaded is exactly the risk the uberjar rework introduced.

## Writing a case

`cases/<area>/<CASE-ID>/` with two files.

`config.json` is a real, complete SFC configuration — runnable by hand, which is what makes a failure
tractable. The report prints the exact command. Parameterise with `${SFC_E2E_SINK}` and friends; SFC
substitutes them itself and **errors on an unresolved placeholder**, so a typo fails loudly instead of
writing somewhere unexpected.

`case.json` is the contract:

```json
{
  "id": "CORE-SIM-COUNTER-01",
  "title": "one line, shown in the report",
  "area": "simulator",
  "tier": "core",
  "intent": "what regression this catches, and why it is written this way",
  "pins": ["path/to/Source.kt:123"],
  "records": 12,
  "timeoutSeconds": 60,
  "modeParity": true,
  "assert": [ { "kind": "channelSequence", "source": "sim", "channel": "ctr", "step": 1 } ]
}
```

`records` is the gate. The runner waits for exactly that many records to reach the sink and then stops
SFC — **nothing sleeps**. `Counter` advances once per read, so the expected values are a function of read
count alone and the wall clock is irrelevant.

Two rules worth knowing before writing assertions:

- **Never assume SIGTERM flushes.** `sfc-main` installs no shutdown hook (only `sfc-ipc` does), so
  buffered target data is lost on stop. Cases force a flush with `"BufferCount": 1` and wait for records.
- **Only assert ordering where the transport guarantees it.** The file sink preserves pipeline order, so
  `channelSequence` is valid. Over SQS or SNS→SQS nothing is ordered — use `channelValueRun`, which checks
  the value *set* is a contiguous run.

Assertion kinds are in [`lib/asserts.py`](lib/asserts.py): `recordCount`, `everyRecord`, `keysAbsent`,
`channelSequence`, `channelValueRun`, `channelValueSet`, `channelValueIn`, `channelNumericRange`,
`deepEquals`, `logContains`, `logAbsent`, `exitCode`, `metric`.

## Known defects

Some cases guard bugs that are **not fixed**, because this suite changes no SFC source file. Those carry
both expectations:

```json
"knownDefect": {
  "ref": "core/sfc-core/.../transformations/Log2.kt:21",
  "summary": "Log2 applies ln() to every non-Float input",
  "assertCurrent": [ ... ],
  "assertCorrect": [ ... ]
}
```

By default the runner asserts `assertCurrent`, so the case is green and **pins** today's behaviour. If
someone fixes the bug the case goes red and the report says the defect looks fixed — flip it to
`assertCorrect`. Each defect becomes a tracked, self-announcing item rather than red noise or a forgotten
note.

Prove a defect case actually discriminates:

```shell
tests/e2e/run.py --area transformations --known-defects assert-correct   # must FAIL
tests/e2e/run.py --area transformations                                  # must PASS
```

A case that passes both ways is worthless and should be rewritten.

## Two oracles

Payload assertions prove data arrived. `tests/e2e-support`'s `E2eMetricsWriter` appends SFC's *own*
per-target counters — `Writes`, `WriteSuccess`, `WriteErrors`, `Messages`, `BytesWritten` — to a local
JSONL file, and the runner fails any case whose target reported a non-zero `WriteErrors` even when every
payload assertion passed. That combination is the signature of a target that drops data and still exits 0,
and it is invisible to payload assertions alone.

## Running it in AWS

`ci/` holds a CDK stack with a CodeBuild project that builds **the current working tree, uncommitted
changes included**, runs the suite and tears its resources down.

```shell
cd ci/cdk && npm install
npx cdk deploy -c githubRepo=<owner>/<repo> [-c oidcProviderArn=<existing>]

# then, from the repo root, against whatever is in your tree right now
SFC_IT_BUCKET=<ArtifactsBucket output> ci/start-build.sh --tiers core
```

`.github/workflows/integration-test.yml` does the same on every push to every branch, once the
`SFC_IT_BUCKET`, `SFC_IT_ROLE_ARN` and `SFC_IT_REGION` repository variables are set from the stack
outputs. Without them the job warns and skips rather than failing.

## Not covered yet

- **AWS-tier cases.** The stack, IAM, provisioning, teardown and reporting are in place and the runner
  handles the tier, but the per-target AWS cases themselves are the next increment.
- **AWS SiteWise Edge.** It writes to an on-premises Greengrass gateway endpoint, so there is no
  cloud-testable path. It is reported as skipped with that reason rather than quietly omitted.
- **The 15 protocol adapters.** This suite covers the core and the targets; the adapter side needs device
  simulators and is its own effort.
