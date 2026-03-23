import { awscdk } from 'projen';
import { NodePackageManager } from 'projen/lib/javascript';
const SDK_VERSION = '3.699.0';
const project = new awscdk.AwsCdkTypeScriptApp({
  cdkVersion: '2.195.0',
  github: false,
  defaultReleaseBranch: 'main',
  name: 'agentic-voice-assistant-on-aws',
  projenrcTs: true,
  packageManager: NodePackageManager.PNPM,
  projenCommand: 'pnpm dlx projen',
  minNodeVersion: '20.12.0',
  deps: [
    `@aws-sdk/client-textract@^${SDK_VERSION}`,
    `@aws-sdk/client-sagemaker-runtime@^${SDK_VERSION}`,
    `@aws-sdk/client-bedrock-runtime@^${SDK_VERSION}`,
    '@aws-cdk/lambda-layer-kubectl-v33@^2.0.0',
    '@types/aws-lambda@^8.10.145',
    '@types/js-yaml@^4.0.9',
    '@types/jsonwebtoken@^9.0.2',
    '@types/lodash@^4.17.20',
    '@types/lodash.merge@^4.6.9',
    'aws-cdk@^2.195.0',
    'commander@^12.1.0',
    '@commander-js/extra-typings@^12.1.0',
    'enquirer@^2.4.1',
    'axios@^1.7.7',
    'jsonwebtoken@^9.0.2',
    'js-yaml@^4.1.0',
    'lodash@^4.17.21',
    'lodash.merge@^4.6.2',
    'cdk-nag@^2.36.1',
  ],
  devDeps: [
    '@types/jsonwebtoken@^9.0.2',
  ],
  gitignore: [],
  tsconfig: {
    compilerOptions: {
      target: 'ES2020',
      lib: ['ES2020', 'DOM'],
      outDir: 'dist',
    },
  },
});
project.setScript('build', 'pnpm dlx projen build && tsc');
project.setScript('deploy:eks', 'DOCKER_DEFAULT_PLATFORM=\'linux/amd64\' DEPLOY_PLUGINS=false DEPLOY_PODS=false npx cdk deploy --all --disable-rollback --require-approval never');
project.setScript('deploy:plugin', 'DOCKER_DEFAULT_PLATFORM=\'linux/amd64\' DEPLOY_PLUGINS=true npx cdk deploy --all --disable-rollback --require-approval never');
project.setScript('deploy:pod', 'DOCKER_DEFAULT_PLATFORM=\'linux/amd64\' DEPLOY_PLUGINS=true DEPLOY_PODS=true npx cdk deploy --all --disable-rollback --require-approval never');
project.setScript('destroy:pod', 'DOCKER_DEFAULT_PLATFORM=\'linux/amd64\' DEPLOY_PLUGINS=true npx cdk deploy --all --disable-rollback --require-approval never');
project.setScript('destroy:plugin', 'DOCKER_DEFAULT_PLATFORM=\'linux/amd64\' DEPLOY_PLUGINS=false DEPLOY_PODS=false npx cdk deploy --all --disable-rollback --require-approval never');
project.setScript('destroy:eks', 'npx cdk destroy --all');
project.setScript('config', 'node ./dist/cli/magic.js config');
project.synth();
