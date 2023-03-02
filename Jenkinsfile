#!/usr/bin/env groovy

node {
    wrap([$class: "BuildUser"]) {
        checkout scm
        def buildlib = load("pipeline-scripts/buildlib.groovy")
        def commonlib = buildlib.commonlib
        commonlib.describeJob("sign-artifacts2", """
            <h2>Sign OCP4 release image / clients and publish signatures</h2>
            <b>Timing</b>: The "promote-assembly" job runs this after a release is accepted.
            Can be run manually if that fails.

            See https://github.com/openshift/art-docs/blob/master/4.y.z-stream.md#sign-the-release

            The shasum file for the clients is signed and signatures published next
            to the shasum file itself.
                http://mirror.openshift.com/pub/openshift-v4/<arch>/clients/ocp/
            The release image shasum is signed and the signature published both on
            Google Cloud Storage and mirror:
                <a href="http://mirror.openshift.com/pub/openshift-v4/signatures/openshift/" target="_blank">http://mirror.openshift.com/pub/openshift-v4/signatures/openshift/</a>
        """)


        // Expose properties for a parameterized build
        properties(
            [
                [
                    $class: 'ParametersDefinitionProperty',
                    parameterDefinitions: [
                        choice(
                            name: 'ENV',
                            description: 'Which environment to sign in',
                            choices: [
                                "stage",
                                "prod",
                            ].join("\n"),
                        ),
                        choice(
                            name: 'KEY_NAME',
                            description: 'Which key to sign with',
                            choices: [
                                "test",
                                "beta2",
                                "redhatrelease2",
                            ].join("\n"),
                        ),
                        choice(
                            name: 'PRODUCT',
                            description: 'Which product to sign',
                            choices: [
                                "openshift",
                                "rhcos",
                                "coreos-installer",
                            ].join("\n"),
                        ),
                        string(
                            name: 'NAME',
                            description: 'Release name (e.g. 4.2.0)',
                            defaultValue: "",
                            trim: true,
                        ),
                        text(
                            name: 'JSON_DIGESTS',
                            description: 'List of json digests to sign; Each line contains an entry in the format of PULLSPEC DIGEST',
                            defaultValue: "",
                        ),
                        text(
                            name: 'MESSAGE_DIGEST_FILES',
                            description: 'List of message digest files to sign; Each line contains an entry; File paths are relative to the signing staging directory.',
                            defaultValue: "",
                        ),
                        separator(name: 'separator-fd608eda-58f5-442c-9765-3203d6abf11a'),
                        commonlib.dryrunParam('Only do dry run test and exit\nDoes not send anything over the bus'),
                        commonlib.mockParam(),
                    ]
                ],
                disableResume()
            ]
        )

        commonlib.checkMock()

        def buildUserId = (env.BUILD_USER_ID == null) ? "automated-process" : env.BUILD_USER_ID
        def json_digests = params.JSON_DIGESTS.trim()
        def message_digest_files = params.MESSAGE_DIGEST_FILES.trim()

        def LOCAL_SIGNATURE_BASE_DIR = "${WORKSPACE}/signatures"
        def BASE_SIGNING_STAGING_DIR = "/mnt/nfs/signing_staging/openshift-v4/"

        stage("initialize") {
            if (buildUserId == "automated-process") {
                echo("Automated sign request started: manually setting signing requestor")
            }
            echo("Submitting ${params.ENV} signing requests as user: ${buildUserId}")
        }

        stage("sign-openshift") {
            buildlib.cleanWorkdir("./artcd_working")
            sh "mkdir -p ./artcd_working"
            sh "rm -rf $LOCAL_SIGNATURE_BASE_DIR && mkdir -p $LOCAL_SIGNATURE_BASE_DIR"

            def cmd = [
                "artcd",
                "-v",
                "--working-dir=./artcd_working",
                "--config", "./config/artcd.toml",
            ]

            if (params.DRY_RUN) {
                cmd << "--dry-run"
            }
            cmd += [
                "sign-artifacts",
                "--env", params.ENV,
                "--sig-keyname", params.KEY_NAME,
                "--product", params.PRODUCT,
                "--release", params.NAME,
                "--out-dir", LOCAL_SIGNATURE_BASE_DIR,
                "--message-digests-dir", BASE_SIGNING_STAGING_DIR,
                "--requestor", "${buildUserId}",
            ]
            if (json_digests) {
                for (json_digest in json_digests.split("[,\n]+")) {
                    cmd << "--json-digest"
                    cmd.addAll(json_digest.trim().split("[\\s]+"))
                }
            }
            if (message_digest_files) {
                for (file_path in message_digest_files.split("[,\n]+")) {
                    file_path = file_path.trim()
                    cmd << "--message-digest" << file_path
                }
            }
            def ssl_cert_id = params.ENV == "prod" ? "0xffe0b38-openshift-art-bot" : "0xffe0b39-nonprod-openshift-art-bot"
            buildlib.withAppCiAsArtPublish() {
                withCredentials([
                    string(credentialsId: 'art-bot-slack-token', variable: 'SLACK_BOT_TOKEN'),
                    file(credentialsId: "${ssl_cert_id}.crt", variable: 'busCertificate'),
                    file(credentialsId: "${ssl_cert_id}.key", variable: 'busKey')
                ]) {
                    cmd << "--ssl-cert" << "${busCertificate}"
                    cmd << "--ssl-key" << "${busKey}"
                    withEnv(["PATH+GSUTIL=/mnt/nfs/home/jenkins/google-cloud-sdk/bin"]) {
                        timeout(time: 15, unit: 'MINUTES') {
                            commonlib.shell(script: cmd.join(' '))
                        }
                    }
                }
            }
        }
    }
}
