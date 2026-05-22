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
        choice(
            name:    'SERVER_IP',
            choices: ['10.35.121.11', '10.35.121.9'],
            description: '部署服务器（测试: .11 / 开发: .9）'
        )
        string(
            name:         'PORT',
            defaultValue: '10107',
            description:  '服务暴露端口'
        )
        string(
            name:         'DATA_DIR',
            defaultValue: '/data/erp-ai-python',
            description:  '数据持久化目录（SQLite + ChromaDB），统一挂载到此路径'
        )
        string(
            name:         'ERP_BASE_URL',
            defaultValue: 'http://10.35.121.11:10101',
            description:  'ERP 后端地址'
        )
        string(
            name:         'DEFAULT_MODEL',
            defaultValue: 'anthropic/claude-3.5-sonnet',
            description:  '默认 AI 模型'
        )
        string(
            name:         'MAX_TOOL_ROUNDS',
            defaultValue: '3',
            description:  '最大工具调用轮次'
        )
        string(
            name:         'ENCRYPTION_SECRET',
            defaultValue: '64d54315912b60f076c083a59b144581',
            description:  'Key 加密密钥（32位），勿修改否则已存 Key 失效'
        )
        string(name: 'REMARK', defaultValue: '', description: '备注')
    }

    stages {

        // ── 1. 初始化变量 ──────────────────────────────────────────────────
        stage('Prepare') {
            steps {
                script {
                    echo "===== [Prepare] 开始初始化 ====="

                    env.APP_BRANCH = params.GIT_BRANCH.replaceAll('origin/', '')

                    env.IMAGE_NAME     = "${PROJECT_NAME}_image_${env.APP_BRANCH}"
                    def timestamp      = new Date().format('yyyyMMddHHmm')
                    env.IMAGE_TAG      = "${params.ENV.toLowerCase()}-${env.BUILD_NUMBER}-${timestamp}"
                    env.FULL_IMAGE     = "${HARBOR_URL}/${env.IMAGE_NAME}:${env.IMAGE_TAG}"
                    env.CONTAINER_NAME = "${PROJECT_NAME}_${env.APP_BRANCH}_${params.PORT}"

                    echo "分支:     ${env.APP_BRANCH}"
                    echo "环境:     ${params.ENV}"
                    echo "镜像:     ${env.FULL_IMAGE}"
                    echo "容器:     ${env.CONTAINER_NAME}"
                    echo "部署到:   ${params.SERVER_IP}:${params.PORT}"
                    echo "数据目录: ${params.DATA_DIR}"
                    echo "===== [Prepare] 初始化完成 ====="

                    def remark = params.REMARK?.trim() ? " | 📝 ${params.REMARK}" : ''
                    currentBuild.description = "${env.APP_BRANCH} | ${params.ENV} | ${params.SERVER_IP}:${params.PORT}${remark}"
                }
            }
        }

        // ── 2. 拉取代码 ────────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                script {
                    echo "===== [Checkout] 拉取分支: ${env.APP_BRANCH} ====="
                }
                checkout scmGit(
                    branches: [[name: "${env.APP_BRANCH}"]],
                    userRemoteConfigs: [[
                        credentialsId: 'jenkins-10.35.121.11@zuru.com',
                        url: "${env.REPO_URL}"
                    ]]
                )
                script {
                    echo "===== [Checkout] 拉取完成 ====="
                }
            }
        }

        // ── 3. 构建镜像并推送到 Harbor（pip install 在镜像内执行）─────────
        stage('Docker Build & Push') {
            steps {
                echo "===== [Docker Build & Push] 开始构建镜像 ====="
                withCredentials([usernamePassword(credentialsId: 'harbor-credential', usernameVariable: 'HARBOR_USER', passwordVariable: 'HARBOR_PASS')]) {
                    sh """
                        docker image prune -f --filter "until=2h"

                        docker login ${HARBOR_URL.tokenize('/')[0]} -u ${HARBOR_USER} -p ${HARBOR_PASS}

                        docker build --no-cache \
                            --build-arg ENV=${params.ENV} \
                            -t ${env.FULL_IMAGE} .
                        echo "镜像构建完成: ${env.FULL_IMAGE}"

                        docker push ${env.FULL_IMAGE}
                        echo "镜像推送完成: ${env.FULL_IMAGE}"

                        docker tag ${env.FULL_IMAGE} ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest
                        docker push ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest

                        docker rmi ${env.FULL_IMAGE} || true
                        docker rmi ${HARBOR_URL}/${env.IMAGE_NAME}:${env.APP_BRANCH}-latest || true
                    """
                }
                echo "===== [Docker Build & Push] 完成 ====="
            }
        }

        // ── 4. 清理旧容器 ──────────────────────────────────────────────────
        stage('Docker Cleanup') {
            steps {
                echo "===== [Docker Cleanup] 清理旧容器 ====="
                script {
                    def cleanupCmd = """
                        echo "清理占用端口 ${params.PORT} 的容器"
                        docker ps -a --format "{{.ID}}" --filter "publish=${params.PORT}" | xargs -r docker stop
                        docker ps -a --format "{{.ID}}" --filter "publish=${params.PORT}" | xargs -r docker rm -f

                        echo "停止并删除容器: ${env.CONTAINER_NAME}"
                        docker ps --filter name=^/${env.CONTAINER_NAME}\$ -q | xargs -r docker stop
                        docker ps -a --filter name=^/${env.CONTAINER_NAME}\$ -q | xargs -r docker rm -f
                    """

                    if (params.SERVER_IP == '10.35.121.11') {
                        sh cleanupCmd
                    } else {
                        def cleanupScript = "${env.WORKSPACE}/.tmp_cleanup_${env.BUILD_NUMBER}.sh"
                        writeFile file: cleanupScript, text: cleanupCmd
                        withCredentials([sshUserPrivateKey(credentialsId: 'dev-server-ssh-key', keyFileVariable: 'SSH_KEY')]) {
                            sh "chmod 600 \$SSH_KEY && ssh -i \$SSH_KEY -o StrictHostKeyChecking=no erppre@${params.SERVER_IP} bash -s < ${cleanupScript}"
                        }
                        sh "rm -f ${cleanupScript} || true"
                    }
                }
                echo "===== [Docker Cleanup] 清理完成 ====="
            }
        }

        // ── 5. 拉取镜像并启动容器 ──────────────────────────────────────────
        stage('Docker Pull & Run') {
            steps {
                echo "===== [Docker Pull & Run] 开始部署 ====="
                script {
                    withCredentials([
                        usernamePassword(credentialsId: 'harbor-credential', usernameVariable: 'HARBOR_USER', passwordVariable: 'HARBOR_PASS')
                    ]) {
                        def harborRegistry = HARBOR_URL.tokenize('/')[0]
                        def deployCmd = """
                            docker login ${harborRegistry} -u ${HARBOR_USER} -p ${HARBOR_PASS}
                            docker pull ${env.FULL_IMAGE}
                            echo "镜像拉取完成: ${env.FULL_IMAGE}"

                            # 创建数据持久化目录
                            mkdir -p ${params.DATA_DIR}

                            docker run -d \\
                                -p ${params.PORT}:3001 \\
                                -e ENV=${params.ENV.toLowerCase()} \\
                                -e ERP_BASE_URL=${params.ERP_BASE_URL} \\
                                -e DEFAULT_MODEL=${params.DEFAULT_MODEL} \\
                                -e MAX_TOOL_ROUNDS=${params.MAX_TOOL_ROUNDS} \\
                                -e ENCRYPTION_SECRET=${params.ENCRYPTION_SECRET} \\
                                -e TZ=Asia/Shanghai \\
                                -v ${params.DATA_DIR}:/app/data \\
                                --log-opt max-size=100m \\
                                --log-opt max-file=3 \\
                                --restart=always \\
                                --name ${env.CONTAINER_NAME} \\
                                ${env.FULL_IMAGE}

                            echo "===== 容器启动状态 ====="
                            docker ps --filter name=^/${env.CONTAINER_NAME}\$ --format "ID: {{.ID}} | 名称: {{.Names}} | 镜像: {{.Image}} | 状态: {{.Status}} | 端口: {{.Ports}}"
                        """

                        if (params.SERVER_IP == '10.35.121.11') {
                            sh deployCmd
                        } else {
                            def deployScript = "${env.WORKSPACE}/.tmp_deploy_${env.BUILD_NUMBER}.sh"
                            writeFile file: deployScript, text: deployCmd
                            withCredentials([sshUserPrivateKey(credentialsId: 'dev-server-ssh-key', keyFileVariable: 'SSH_KEY')]) {
                                sh "chmod 600 \$SSH_KEY && ssh -i \$SSH_KEY -o StrictHostKeyChecking=no erppre@${params.SERVER_IP} bash -s < ${deployScript}"
                            }
                            sh "rm -f ${deployScript} || true"
                        }
                    }
                }
                echo "===== [Docker Pull & Run] 完成 ====="
            }
        }
    }

    post {
        always {
            script {
                if (!env.CONTAINER_NAME) return
                try {
                    def infoCmd = """
                        echo "===== 容器状态 ====="
                        docker ps -a --filter name=^/${env.CONTAINER_NAME}\$ --format "ID: {{.ID}} | 名称: {{.Names}} | 状态: {{.Status}} | 端口: {{.Ports}}"
                        echo "===== 容器日志（最新 50 行）====="
                        docker logs --tail 50 ${env.CONTAINER_NAME} 2>&1 || echo "容器不存在或未启动"
                    """
                    sleep 3
                    if (params.SERVER_IP == '10.35.121.11') {
                        sh infoCmd
                    } else {
                        def infoScript = "${env.WORKSPACE}/.tmp_info_${env.BUILD_NUMBER}.sh"
                        writeFile file: infoScript, text: infoCmd
                        withCredentials([sshUserPrivateKey(credentialsId: 'dev-server-ssh-key', keyFileVariable: 'SSH_KEY')]) {
                            sh "chmod 600 \$SSH_KEY && ssh -i \$SSH_KEY -o StrictHostKeyChecking=no erppre@${params.SERVER_IP} bash -s < ${infoScript} || true"
                        }
                        sh "rm -f ${infoScript} || true"
                    }
                } catch(e) {
                    echo "日志获取失败: ${e.message}"
                }
            }
        }
        success {
            echo "===== 部署成功: ${env.CONTAINER_NAME} @ ${params.SERVER_IP}:${params.PORT} ====="
        }
        failure {
            echo "===== 构建或部署失败 ====="
        }
    }
}
