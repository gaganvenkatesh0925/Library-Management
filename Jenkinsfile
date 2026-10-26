
pipeline {
    agent any

    parameters {
        choice(
            name: 'ACTION',
            choices: ['DEPLOY', 'CLEANUP'],
            description: 'Select DEPLOY to install/update or CLEANUP to uninstall'
        )
    }

    environment {
        IMAGE = 'gagan0925/library-management'
        PROJECT = '/media/sf_Library-Management'
        KUBECONFIG = '/var/lib/jenkins/.kube/config'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build & Push') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                script {
                    env.TAG = "build-${env.BUILD_NUMBER}"
                }

                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_TOKEN'
                )]) {
                    sh '''
                        set -eu
                        trap 'docker logout >/dev/null 2>&1 || true' EXIT

                        printf '%s' "$DOCKER_TOKEN" |
                            docker login -u "$DOCKER_USER" --password-stdin

                        docker build -t "$IMAGE:$TAG" .
                        docker push "$IMAGE:$TAG"
                    '''
                }
            }
        }

        stage('Deploy') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                sh '''
                    set -eu
                    cd "$PROJECT/ansible"

                    ansible-playbook library-automation.yml \
                        --tags install \
                        --extra-vars "library_image_tag=$TAG"
                '''
            }
        }

        stage('Verify') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                sh '''
                    set -eu

                    kubectl -n library-app rollout status \
                        deployment/library --timeout=180s

                    kubectl -n library-app get pods,services
                '''
            }
        }

        stage('Cleanup') {
            when {
                expression { params.ACTION == 'CLEANUP' }
            }
            steps {
                sh '''
                    set -eu
                    cd "$PROJECT/ansible"

                    ansible-playbook library-automation.yml \
                        --tags uninstall
                '''
            }
        }
    }

    post {
        success {
            script {
                if (params.ACTION == 'DEPLOY') {
                    echo "Deployment successful: ${IMAGE}:${env.TAG}"
                } else {
                    echo 'Cleanup completed successfully.'
                }
            }
        }

        failure {
            echo 'Pipeline failed. Check the stage logs.'
        }
    }
}
