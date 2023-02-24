#!/usr/bin/env groovy

node {
    checkout scm
    def release = load("pipeline-scripts/release.groovy")
    def buildlib = release.buildlib
    def commonlib = buildlib.commonlib
    def slacklib = commonlib.slacklib
    commonlib.describeJob("promote-assembly", """
        <h2>Publish official OCP 4 release artifacts</h2>
        <b>Timing</b>: <a href="https://github.com/openshift/art-docs/blob/master/4.y.z-stream.md#create-the-release-image" target="_blank">4.y z-stream doc</a>

        Be aware that by default the job stops for user input very early on. It
        sends slack alerts in our release channels when this occurs.

        For more details see the <a href="https://github.com/openshift/aos-cd-jobs/blob/master/jobs/build/promote/README.md" target="_blank">README</a>
    """)


    // Expose properties for a parameterized build
    properties(
        [
            disableResume(),
            buildDiscarder(
                logRotator(
                    artifactDaysToKeepStr: '',
                    artifactNumToKeepStr: '',
                    daysToKeepStr: '',
                    numToKeepStr: '')),
            [
                $class: 'ParametersDefinitionProperty',
                parameterDefinitions: [
                    commonlib.ocpVersionParam('VERSION', '4'),  // not used by "stream" assembly
                    string(
                        name: 'ASSEMBLY',
                        description: 'The name of an assembly to promote.',
                        defaultValue: "stream",
                        trim: true,
                    ),
                    booleanParam(
                        name: 'NO_MULTI',
                        description: 'Do not promote a multi-arch/heterogeneous payload.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'MULTI_ONLY',
                        description: 'Do not promote arch-specific homogenous payloads.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'PERMIT_PAYLOAD_OVERWRITE',
                        description: 'DO NOT USE without team lead approval. Allows the pipeline to overwrite an existing payload in quay.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_MIRROR_BINARIES',
                        description: 'Do not mirror binaries. Useful in case of reruns on subsequent failure',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_CINCINNATI_PR_CREATION',
                        description: 'DO NOT USE without team lead approval. This is an unusual option.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_OTA_SLACK_NOTIFICATION',
                        description: 'Do not notify OTA team in slack for new PRs',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_BUILD_MICROSHIFT',
                        description: 'Do not trigger build-microshift job',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_IMAGE_LIST',
                        description: '(Standard Release) Do not gather an advisory image list for docs.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_ATTACHED_BUG_CHECK',
                        description: 'Skip attached bug check',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_ATTACH_CVE_FLAWS',
                        description: 'Do not attach CVE flaws bugs',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'SKIP_SIGNING',
                        description: 'Do not sign the release.',
                        defaultValue: false,
                    ),
                    booleanParam(
                        name: 'FORCE_RHCOS_SYNC',
                        description: '(Standard Release) Always sync RHCOS images to mirrors.',
                        defaultValue: false,
                    ),
                    string(
                        name: 'MAIL_LIST_SUCCESS',
                        description: 'Success Mailing List',
                        defaultValue: [
                            'aos-cicd@redhat.com',
                            'aos-qe@redhat.com',
                            'aos-art-automation+new-release@redhat.com',
                        ].join(','),
                        trim: true,
                    ),
                    commonlib.dryrunParam('Take no actions. Note: still notifies and runs signing job (which fails)'),
                    commonlib.mockParam(),
                ]
            ],
        ]
    )

    commonlib.checkMock()
    def (major, minor) = commonlib.extractMajorMinorVersionNumbers(params.VERSION)
    def skipAttachedBugCheck = params.SKIP_ATTACHED_BUG_CHECK
    def next_minor = "${major}.${minor + 1}"
    if (params.DRY_RUN) {
        currentBuild.displayName += " (dry-run)"
        currentBuild.description += " [DRY RUN]"
    }
    currentBuild.displayName += " ${params.VERSION} - ${params.ASSEMBLY}"

    stage("Initialize") {
        // Install pyartcd
        commonlib.shell(script: "pip install -e ./pyartcd")
        // must be able to access remote registry for verification
        buildlib.registry_quay_dev_login()
    }

    // release_info is the output of `artcd promote` command.
    // It is a dict containing the information of the promoted release.
    // e.g. {"group": "openshift-4.8", "assembly": "4.8.28", "type": "standard", "name": "4.8.28", "content": {"s390x": {"pullspec": "quay.io/openshift-release-dev/ocp-release:4.8.28-s390x", "digest": "sha256:b33d11a797022f9394aca5f05f1fcba8faa3fcc607f0cdd6e75666f8f93e7141", "from_release": "registry.ci.openshift.org/ocp-s390x/release-s390x:4.8.0-0.nightly-s390x-2022-01-19-035735", "rhcos_version": "48.84.202201111102-0"}, "x86_64": {"pullspec": "quay.io/openshift-release-dev/ocp-release:4.8.28-x86_64", "digest": "sha256:ba1299680b542e46744307afc7effc15957a20592d88de4651610b52ed8be9a8", "from_release": "registry.ci.openshift.org/ocp/release:4.8.0-0.nightly-2022-01-19-035759", "rhcos_version": "48.84.202201102304-0"}, "ppc64le": {"pullspec": "quay.io/openshift-release-dev/ocp-release:4.8.28-ppc64le", "digest": "sha256:791790c88018eb9848765797f4348d4d5161dc342c61ec67d41770873e574a43", "from_release": "registry.ci.openshift.org/ocp-ppc64le/release-ppc64le:4.8.0-0.nightly-ppc64le-2022-01-19-035729", "rhcos_version": "48.84.202201102304-0"}}, "justifications": [], "advisory": 87060, "live_url": "https://access.redhat.com/errata/RHBA-2022:0172"}
    def release_info = [:]

    stage("promote release") {
        sh "rm -rf ./artcd_working && mkdir -p ./artcd_working"
        def cmd = [
            "artcd",
            "-v",
            "--working-dir=./artcd_working",
            "--config=./config/artcd.toml",
        ]
        if (params.DRY_RUN) {
            cmd << "--dry-run"
        }
        cmd += [
            "promote",
            "--group=openshift-${params.VERSION}",
            "--assembly=${params.ASSEMBLY}",
        ]
        if (skipAttachedBugCheck) {
            cmd << "--skip-attached-bug-check"
        }
        if (params.SKIP_IMAGE_LIST) {
            cmd << "--skip-image-list"
        }
        if (params.SKIP_ATTACH_CVE_FLAWS) {
            cmd << "--skip-attach-cve-flaws"
        }
        if (params.PERMIT_PAYLOAD_OVERWRITE) {
            cmd << "--permit-overwrite"
        }
        if (params.NO_MULTI) {
            cmd << "--no-multi"
        }
        if (params.MULTI_ONLY) {
            cmd << "--multi-only"
        }
        if (major == 4 && minor <= 11) {
            // Add '-multi' to heterogeneous payload name to workaround a Cincinnati issue (#incident-cincinnati-sha-mismatch-for-multi-images).
            // This is also required for 4.11 to prevent the heterogeneous payload from getting into Cincinnati channels
            // because 4.11 heterogeneous is tech preview.
            cmd << "--use-multi-hack"
        }
        echo "Will run ${cmd}"
        buildlib.withAppCiAsArtPublish() {
            withCredentials([string(credentialsId: 'art-bot-slack-token', variable: 'SLACK_BOT_TOKEN'), string(credentialsId: 'jboss-jira-token', variable: 'JIRA_TOKEN')]) {
                def out = sh(script: cmd.join(' '), returnStdout: true).trim()
                echo "artcd returns:\n$out"
                release_info = readJSON(text: out)
            }
        }
    }

    buildlib.registry_quay_dev_login()  // chances are, earlier auth has expired

    def justifications =release_info.justifications ?: []
    def quay_url = "quay.io/openshift-release-dev/ocp-release"
    def client_type = 'ocp'
    if ((release_info.type == "candidate" && !release_info.assembly.startsWith('rc.')) || release_info.type == "custom" || release_info.type == "preview") {
        // Feature candidates and custom releases and .next "preview" releases use client_type ocp-dev-preview and beta2 signing key.
        client_type = 'ocp-dev-preview'
    }
    def message_digest_files = []
    stage("mirror binaries") {
        if (params.SKIP_MIRROR_BINARIES) {
            echo "Skip mirroring binaries."
            return
        }
        // Remove signing staging directory
        // def BASE_SIGNING_STAGING_DIR = "/mnt/nfs/signing_staging/openshift-v4"
        sh "rm -rf /mnt/nfs/signing_staging/openshift-v4"
        release_info.content.each { arch, info ->
            echo "Mirroring client binaries for $arch"
            def dest_release_tag = release.destReleaseTag(release_info.name, arch)
            // Currently a multi/heterogeneous release payload has a modified release name to workaround a Cincinnati issue.
            // Using the real per-arch release name in $info instead of the one defined by release artists.
            def release_name = info.metadata.version
            if (!params.DRY_RUN) {
                // def SIGNING_STAGING_DIR = "${BASE_SIGNING_STAGING_DIR}/${arch}/clients/${client_type}/${release_name}"
                if (arch != "multi") {
                    release.stagePublishClient(quay_url, dest_release_tag, release_name, arch, client_type)
                } else {
                    release.stagePublishMultiClient(quay_url, dest_release_tag, release_name, client_type)
                }
                message_digest_files << "${arch}/clients/${client_type}/${release_name}/sha256sum.txt"
            } else {
                echo "[DRY RUN] Would have sync'd client binaries for ${quay_url}:${dest_release_tag} to mirror ${arch}/clients/${client_type}/${release_name}."
            }
        }
    }

    stage("sync RHCOS") {
        /*
         * This has inappropriate logic, disabling it for now.
         * Current behavior is to look up rhcos version of machine-os-content
         * under some circumstances, and to put the result on mirror.
         * Behavior should be to look up the rhcos version in
         * https://github.com/openshift/installer/blob/release-4.10/data/data/coreos/rhcos.json
         * from the commit of installer, and ensure `latest-<version>` points to there.

        def is_prerelease = release_info.type == "candidate"
        if (release_info.type == "custom") {
            echo "Skipping RHCOS sync for a custom release."
            return
        }
        if (!is_prerelease && !params.FORCE_RHCOS_SYNC) {
            echo "Skipping RHCOS sync for a ${release_info.type} release."
            return
        }
        def rhcos_mirror_prefix = is_prerelease ? "pre-release" : "$major.$minor"
        for (arch in arches) {
            arch = commonlib.brewArchForGoArch(arch)
            def rhcos_build = release_info.content[arch].rhcos_version
            if (!rhcos_build) {
                echo "Skip mirroring RHCOS for $arch"
                continue
            }
            print("RHCOS build for $arch: $rhcos_build")
            def sync_params = [
                buildlib.param('String','OCP_VERSION', "$major.$minor"),
                buildlib.param('String','OVERRIDE_NAME', release_info.name),
                buildlib.param('String','ARCH', arch),
                buildlib.param('String','MIRROR_PREFIX', rhcos_mirror_prefix),
                buildlib.param('String','OVERRIDE_BUILD', rhcos_build),
                booleanParam(name: 'DRY_RUN', value: params.DRY_RUN),
                booleanParam(name: 'MOCK', value: params.MOCK)
            ]
            build(
                job: '/aos-cd-builds/build%252Frhcos_sync',
                propagate: false,
                parameters: sync_params
            )
        }
        */
    }

    stage("sign artifacts") {
        if (params.SKIP_SIGNING) {
            echo "Signing artifacts is skipped."
            return
        }
        def json_digests = []
        release_info.content.each { arch, info ->
            json_digests << "${release_info.content[arch].pullspec} ${release_info.content[arch].digest}"
        }
        build(
            job: "/signing-jobs/signing%2Fsign-artifacts2",
            propagate: true,
            parameters: [
                booleanParam(name: "DRY_RUN", value: params.DRY_RUN),
                string(name: "ENV", value: "prod"),
                string(name: "KEY_NAME", value: client_type=='ocp'?"redhatrelease2":"beta2"),
                string(name: "PRODUCT", value: "openshift"),
                string(name: "NAME", value: release_name),
                string(name: "JSON_DIGESTS", value: json_digests.join('\n')),
                string(name: "MESSAGE_DIGEST_FILES", value: message_digest_files),
            ]
        )
    }

    // stage("send release message") {
    //     if (release_info.type == "custom") {
    //         echo "Don't send release messages for a custom release."
    //         return
    //     }
    //     if (params.SKIP_SIGNING) {
    //         echo "Don't send release messages because SKIP_SIGNING is set."
    //         return
    //     }
    //     if (params.DRY_RUN) {
    //         echo "DRY_RUN: Would have sent release messages."
    //         return
    //     }

    //     release_info.content.each { arch, info ->
    //         // Currently a multi/heterogeneous release payload has a modified release name to workaround a Cincinnati issue.
    //         // Using the real per-arch release name in $info instead of the one defined by release artists.
    //         def release_name = info.metadata.version
    //         release.sendReleaseCompleteMessage(["name": release_name], release_info.advisory ?: 0, release_info.live_url, arch)
    //     }
    // }

    // stage("channel prs") {
    //     if (release_info.type == "custom") {
    //         echo "Skipping PR creation for custom (hotfix) release."
    //         return
    //     }
    //     if (params.SKIP_CINCINNATI_PR_CREATION) {
    //         echo "Don't create Cincinnati PRs because SKIP_CINCINNATI_PR_CREATION is set"
    //         return
    //     }
    //     if (params.DRY_RUN) {
    //         echo "[DRY RUN] Would have created Cincinnati PRs."
    //         return
    //     }
    //     def candidate_pr_note = ""
    //     if (justifications) {
    //         candidate_pr_note += ""
    //         for (String justification: justifications) {
    //             candidate_pr_note += "${justification}\n"
    //         }
    //     }
    //     def from_releases = release_info.content.findAll{ k, v -> v.from_release }.collect {k, v -> v.from_release.split(":")[-1] }
    //     build(
    //         job: '/aos-cd-builds/build%2Fcincinnati-prs',  propagate: true,
    //         parameters: [
    //             buildlib.param('String', 'FROM_RELEASE_TAG', from_releases.join(",")),
    //             buildlib.param('String', 'RELEASE_NAME', release_info.name),
    //             buildlib.param('String', 'ADVISORY_NUM', "${release_info.advisory?: 0}"),
    //             buildlib.param('String', 'GITHUB_ORG', 'openshift'),
    //             buildlib.param('String', 'CANDIDATE_PR_NOTE', candidate_pr_note),
    //             booleanParam(name: 'SKIP_OTA_SLACK_NOTIFICATION', value: params.SKIP_OTA_SLACK_NOTIFICATION)
    //         ]
    //     )
    // }

    stage("validate RHSAs") {
        if (release_info.type == "custom" || release_info.type == "preview") {
            echo "Skipping RHSA check for custom (hotfix) or preview release."
            return
        }

        if (params.DRY_RUN) {
            return
        }

        def advisory_map = release.getAdvisories("openshift-${params.VERSION}")?: [:]
        advisory_map.each { k, v ->
            if (v <= 0) {
                return
            }
            advisory_id = "$v"
            res = commonlib.shell(
                script: "${buildlib.ELLIOTT_BIN} validate-rhsa ${advisory_id}",
                returnAll: true,
            )
            if (res.returnStatus != 0) {
                msg = """
                    Review of CVE situation required for advisory <https://errata.devel.redhat.com/advisory/${advisory_id}|${advisory_id}>.
                    Report:
                    ```
                    ${res.stdout}
                    ```
                    Note: For GA image advisories this is expected to fail.
                """.stripIndent()
                slacklib.to(params.VERSION).say(msg)
            }
        }
    }

    stage("trigger build-microshift") {
        if (params.SKIP_BUILD_MICROSHIFT) {
            echo "Don't trigger build-microshift because SKIP_BUILD_MICROSHIFT is set"
            return
        }
        if (major == 4 && minor < 12) {
            echo "Skip microshift build for version < 4.12"
            return
        }
        def mirror_path = "/pockets/microshift/${params.VERSION}-el8/${params.ASSEMBLY}"
        if (commonlib.listS3Mirror(mirror_path + "/plashet.yml")) {
            echo "Microshift for this assembly has been published to the pocket. If a rebuild is required, please manually run build-microshift job."
            return
        }
        build(
            job: "build%2Fbuild-microshift",
            propagate: true,
            parameters: [
                string(name: 'BUILD_VERSION', value: params.VERSION),
                string(name: 'ASSEMBLY', value: params.ASSEMBLY),
                booleanParam(name: 'DRY_RUN', value: params.DRY_RUN),
            ]
        )
    }

    stage("clean and mail") {
        dry_subject = ""
        if (params.DRY_RUN) { dry_subject = "[DRY RUN] "}
        def pullspecs = release_info.content.findAll{ k, v -> v.pullspec }.collect {k, v -> v.pullspec }
        commonlib.email(
            to: "${params.MAIL_LIST_SUCCESS}",
            replyTo: "aos-team-art@redhat.com",
            from: "aos-art-automation@redhat.com",
            subject: "${dry_subject}Success building release payload: ${release_info.name}",
            body: """
Jenkins Job: ${env.BUILD_URL}
PullSpecs: ${pullspecs.join(",")}
        """);
        buildlib.cleanWorkspace()
    }

}
