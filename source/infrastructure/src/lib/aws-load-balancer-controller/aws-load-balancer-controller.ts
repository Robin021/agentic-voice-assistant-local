/**
 *  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
 *  with the License. A copy of the License is located at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
 *  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
 *  and limitations under the License.
 */

import path from 'path';
import { Duration } from 'aws-cdk-lib';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3_assets from 'aws-cdk-lib/aws-s3-assets';
import { Construct } from 'constructs';
import { AwsLoadbalancerControllerIamPolicy } from './iam-policy';

export interface ALBControllerConstructProps {
  readonly cluster: eks.Cluster;
  readonly helmDeployRole: iam.Role;
}

export class ALBControllerConstruct extends Construct {

  readonly albChart: eks.HelmChart;

  constructor(scope: Construct, id: string, props: ALBControllerConstructProps) {
    super(scope, id);

    // Create ALB Load Balancer Controller ServiceAccount
    const albServiceAccount = props.cluster.addServiceAccount('ALBServiceAccount', {
      name: 'aws-load-balancer-controller',
      namespace: 'kube-system',
    });
    AwsLoadbalancerControllerIamPolicy(props.cluster.stack.partition).Statement.forEach((statement: any) => {
      albServiceAccount.addToPrincipalPolicy(iam.PolicyStatement.fromJson(statement));
    });

    const chart_asset = new s3_assets.Asset(this, 'ALBControllerChartAsset', {
      path: path.join(__dirname, '../../../charts/aws-load-balancer-controller/'),
    });
    chart_asset.grantRead(props.helmDeployRole);
    chart_asset.node.addDependency(albServiceAccount);

    this.albChart = props.cluster.addHelmChart('ALBController', {
      release: 'aws-load-balancer-controller',
      chartAsset: chart_asset,
      namespace: 'kube-system',
      wait: true,
      values: {
        clusterName: props.cluster.clusterName,
        serviceAccount: {
          create: false,
          name: albServiceAccount.serviceAccountName,
        },
        nodeSelector: { 'app/voicebot': 'enabled' },
      },
      timeout: Duration.minutes(10),
    });
    this.albChart.node.addDependency(chart_asset);

  }

}