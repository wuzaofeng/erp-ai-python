// ── 构建 Job：拉代码 → 构建镜像 → 推 Harbor ──────────────────────────────
pipeline {
    agent any

    environment {
        REPO_URL     = 'git@10.35.110.18:gitlab-instance-997c3570/AI-python.git'
        PROJECT_NAME = 'erp_ai_python'
        HARBOR_URL   = '10.35.121.11:5000/erp_ai_python'
    }

    parameters {
        gitParameter(
            name:               'GIT_BRANCH',
            type:               'PT_BRANCH',
            defaultValue:       'origin/main',
            branchFilter:       'origin/.*',
            quickFilterEnabled: true,
            description:        '选择构建分支'
        )
        choice(
            name:    'ENV',
            choices: ['Test', 'Dev', 'Pre'],
            description: '部署环境'
        )
        string(name: 'REMARK', defaultValue: '', description: '备注')
    }

    stages {

        // ── 1. 初始化变量 ──────────────────────────────────────────────────
        stage('Prepare') {
            steps {
                script {
                    env.APP_BRANCH = params.GIT_BRANCH.replaceAll('origin/', '')
                    env.IMAGE_NAME = "${PROJECT_NAME}_image_${env.APP_BRANCH}"
                    def timestamp  = new Date().format('yyyyMMddHHmm')
                    env.IMAGE_TAG  = "${params.ENV.toLowerCase()}-${env.BUILD_NUMBER}-${timestamp}"
                    env.FULL_IMAGE = "${HARBOR_URL}/${env.IMAGE_NAME}:${env.IMAGE_TAG}"

                    echo "分支: ${env.APP_BRANCH} | 镜像: ${env.FULL_IMAGE}"

                    def remark = params.REMARK?.trim() ? " | ${params.REMARK}" : ''
                    currentBuild.description = "${env.APP_BRANCH} | ${params.ENV} | Build${remark}"
                }
            }
        }

        // ── 2. 拉取代码 ────────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                checkout scmGit(
                    branches: [[name: "${env.APP_BRANCH}"]],
                    userRemoteConfigs: [[
                        credentialsId: 'jenkins-10.35.121.11@zuru.com',
                        url: "${env.REPO_URL}"
                    ]]
                )
                script { echo "===== [Checkout] 完成 =====" }
            }
        }

        // ── 3. 构建镜像并推送到 Harbor ─────────────────────────────────────
        stage('Docker Build & Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'harbor-credential', usernameVariable: 'HARBOR_USER', passwordVariable: 'HARBOR_PASS')]) {
                    sh """
                        docker image prune -f --filter "until=2h"

                        docker login ${HARBOR_URL.tokenize('/')[0]} -u ${HARBOR_USER} -p ${HARBOR_PASS}

                        docker build --no-cache \
                            --build-arg ENV=${params.ENV} \
                            -t ${env.FULL_IMAGE} .
                        echo "镜像构建完成: ${env.FULL_IMAGE}"

                        docker push ${env.FULL_IMAGE}

                        docker tag ${env.FULL_IMAGE} ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest
                        docker push ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest

                        docker rmi ${env.FULL_IMAGE} || true
                        docker rmi ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest || true

                        echo "===== 构建推送完成: ${env.FULL_IMAGE} ====="
                    """
                }
            }
        }
    }

    post {
        success { echo "===== 构建成功: ${env.FULL_IMAGE} =====" }
        failure { echo "===== 构建失败 =====" }
    }
}
