#!/usr/bin/env groovy
import java.net.URLEncoder

node {
    checkout scm
    def release = load("pipeline-scripts/release.groovy")
    def buildlib = release.buildlib
    def commonlib = release.commonlib

    properties([
            buildDiscarder(
                logRotator(
                    artifactDaysToKeepStr: '',
                    artifactNumToKeepStr: '',
                    daysToKeepStr: '30',
                    numToKeepStr: ''
                )
            ),
            disableResume(),
            disableConcurrentBuilds(),
    ])

    // Send UMB messages for these new nightlies, yields a list like:
    //     [4.6.0-0.nightly, 4.5.0-0.nightly, 4.4.0-0.nightly, ...]
    def nightlies = commonlib.ocp4Versions.collect { it + ".0-0.nightly" }
    // Send UMB messages for these new stables, yields a list like:
    //     [4-stable:4.6, 4-stable:4.5, 4-stable:4.4, ...]
    def stables = commonlib.ocp4Versions.collect { "4-stable:" + it }
    def releaseStreams = stables + nightlies
    currentBuild.description = ""
    currentBuild.displayName = ""

    stage("send UMB messages for new releases") {
        dir ("/mnt/nfs/home/jenkins/.cache/releases") {
            for (String key : releaseStreams) {
                try {
                    def keySplit = key.split(":")  // 4-stable:4.6 -> [4-stable, 4.6]
                    def releaseStream = keySplit[0]
                    def majorMinor = keySplit.length > 1 ? keySplit[1] : null
                    // There are different release controllers for OCP - one for each architecture.
                    def url = "${commonlib.getReleaseControllerURL(releaseStream)}/api/v1/releasestream/${URLEncoder.encode(releaseStream, "utf-8")}/latest"
                    if (majorMinor) {
                        def (major, minor) = commonlib.extractMajorMinorVersionNumbers(majorMinor)
                        def queryParams = [
                            "in": ">${major}.${minor}.0-0 < ${major}.${minor + 1}.0-0"
                        ]
                        def queryString = queryParams.collect {
                                (URLEncoder.encode(it.key, "utf-8") + "=" +  URLEncoder.encode(it.value, "utf-8"))
                            }.join('&')
                        url += "?" + queryString
                    }
                    def response = httpRequest(
                        url: url,
                        httpMode: 'GET',
                        acceptType: 'APPLICATION_JSON',
                        timeout: 30,
                    )
                    latestRelease = readJSON text: response.content
                    latestReleaseVersion = latestRelease.name
                    echo "${releaseStream}: latestRelease=${latestRelease}"
                    try {
                        previousRelease = readJSON(file: "${releaseStream}.current")
                        echo "${releaseStream}: previousRelease=${previousRelease}"
                    } catch (readex) {
                        // The first time this job is ran and the first
                        // time any new release is added the 'readFile'
                        // won't find the file and will raise a
                        // NoSuchFileException exception.
                        echo "${releaseStream}: Error reading revious release: ${readex}"
                        touch file: "${releaseStream}.current"
                        previousRelease = {}
                    }

                    if ( latestRelease != previousRelease ) {
                        def previousReleaseVersion = "0.0.0"
                        if (previousRelease)
                            previousReleaseVersion = previousRelease.name
                        currentBuild.displayName += "🆕 ${releaseStream}: ${previousReleaseVersion} -> ${latestReleaseVersion}"
                        currentBuild.description += "\n🆕 ${releaseStream}: ${previousReleaseVersion} -> ${latestReleaseVersion}"
                        release.sendPreReleaseMessage(latestRelease, releaseStream, "Red Hat UMB (stage)")
                        writeJSON file: "${releaseStream}.current", json: latestRelease
                    } else {
                        currentBuild.description += "\nUnchanged: ${releaseStream}"
                    }
                } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException ex) {
                    // don't try to recover from cancel
                    throw ex
                } catch (ex) {
                    // but do tolerate other per-release errors
                    echo "Error during release ${release}: ${ex}"
                    currentBuild.description += "\nFailed: ${release}"
                }
            }
        }
    }
}
