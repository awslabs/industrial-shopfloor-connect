# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. Ensure the local build passes, see [Building and testing](#building-and-testing).
4. Commit to your fork using clear commit messages.
5. Send us a pull request, answering any default questions in the pull request interface.
6. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.
   Besides the build check, changes run the integration suite in AWS CodeBuild, which tests each case in up to three
   deployment modes (in-process, IPC and uberjar), writing to real AWS services or to local test servers. For pull
   requests from forks it waits for a maintainer's approval. See [ci/README.md](ci/README.md); to add a test case, see
   [ci/e2e/README.md](ci/e2e/README.md).

GitHub provides additional document on [forking a repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo) and
[creating a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).


## Building and testing

Any JDK 17 or newer builds SFC (CI uses Amazon Corretto 21); the Gradle wrapper fetches Gradle itself, and the
product is compiled for Java 17 whichever JDK runs the build.

**Linux / macOS**

```shell
./gradlew build
./sfcup.sh --local
```

**Windows (PowerShell)**

```powershell
.\gradlew.bat build
.\sfcup.ps1 -Local
```

`build` compiles every module, runs the unit tests and writes the release bundles, including `sfc-uberjar.tar.gz`,
to `build/distribution/<module>.tar.gz`. The second command, run from the repository root, installs that local
uberjar in place of the released one, as `sfcx`. If Windows refuses to run the script, use
`powershell -ExecutionPolicy Bypass -File .\sfcup.ps1 -Local`.


## Documentation and examples

A change to the docs or the examples follows these rules:

* Show each configuration in the style of its deployment mode
  ([Configure a component in each mode](docs/sfc-deployment.md#configuration-in-each-mode)):
  uberjar entries name `FactoryClassName` only; in-process entries add
  `"JarFiles": ["${SFC_DEPLOYMENT_DIR}/<module>/lib"]`; IPC configurations have no `AdapterTypes`/`TargetTypes`
  sections, and each adapter names an `AdapterServer` and each target a `TargetServer`, defined under
  `AdapterServers`/`TargetServers`. A `ConfigProvider` or `LogWriter` in the uberjar needs `"JarFiles": []`.
* Every adapter needs its `AdapterType` and every target its `TargetType`, in every mode, set to the component's fixed
  type as listed in [Protocol adapter types and classes](docs/sfc-running-adapters.md#protocol-adapter-types-and-classes)
  and [Target types and classes](docs/sfc-running-targets.md#target-types-and-classes). In the uberjar and in-process
  modes the `AdapterTypes`/`TargetTypes` key is that same value. Instance names, such as the keys under
  `ProtocolAdapters`, `Targets` and `Sources`, are free.
* Every OS-specific step gets a **Linux / macOS** block and a **Windows (PowerShell)** block; a command that is the
  same on every OS gets one unlabelled block. The PowerShell must run in Windows PowerShell 5.1. The installed command
  is `sfcx` on every OS.
* A new or changed example needs its row in the [examples catalog](docs/examples/README.md), a "Docs used" line at
  the end of its README, and an entry in the **Examples:** line of each component page it uses.
* Add a bullet to [RELEASE NOTES.md](RELEASE%20NOTES.md).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.
