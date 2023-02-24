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
                            description: 'Which key to sign with\nIf ENV==stage everything becomes "test"\nFor prod we currently use "redhatrelease2"',
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
                        string(
                            name: 'JSON_DIGESTS',
                            description: 'A comma separated list of json digests to sign; format is <PULLSPEC> <DIGEST>, <PULLSPEC> <DIGEST>, ...',
                            defaultValue: "",
                            trim: true,
                        ),
                        // file(name: 'MESSAGE_DIGEST_FILE', description: 'message digest file to sign'),
                        base64File(
                            name: 'MESSAGE_DIGEST_FILE',
                            description: 'A message digest file to sign',
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

        stage("initialize")
            if ( buildUserId == "automated-process" ) {
                echo("Automated sign request started: manually setting signing requestor")
            }
            echo("Submitting${noop} signing requests as user: ${buildUserId}")
        }

        stage("gen-assembly") {
            buildlib.cleanWorkdir("./artcd_working")
            sh "mkdir -p ./artcd_working"
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
            ]
            if (params.JSON_DIGESTS) {
                for (json_digest in params.JSON_DIGESTS.split("[,]+")) {
                    cmd << "--json-digest"
                    cmd += json_digest.trim().split("[\\s]+")
                }
            }
            buildlib.withAppCiAsArtPublish() {
                withCredentials([
                    string(credentialsId: 'art-bot-slack-token', variable: 'SLACK_BOT_TOKEN'),
                    file(credentialsId: '0xFFE0973-openshift-art-signatory-prod.crt', variable: 'busCertificate'),
                    file(credentialsId: '0xFFE0973-openshift-art-signatory-prod.key', variable: 'busKey')
                ]) {
                    cmd << "--ssl-cert" << "${busCertificate}"
                    cmd << "--ssl-key" << "${busKey}"
                    withFileParameter('MESSAGE_DIGEST_FILE') {
                        echo "MESSAGE_DIGEST_FILE: $MESSAGE_DIGEST_FILE"
                        sh 'cat $MESSAGE_DIGEST_FILE'
                    }
                    commonlib.shell(script: cmd.join(' '))
                }
            }
        }
    }
}
