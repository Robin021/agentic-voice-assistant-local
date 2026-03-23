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


export interface MetricsServerConstructProps {
  readonly cluster: eks.Cluster;
  readonly helmDeployRole: iam.Role;
}

export class MetricsServerConstruct extends Construct {

  readonly metricsServerChart: eks.HelmChart;

  constructor(scope: Construct, id: string, props: MetricsServerConstructProps) {
    super(scope, id);

    // Create ALB Load Balancer Controller ServiceAccount
    const chart_asset = new s3_assets.Asset(this, 'MetricsServerChartAsset', {
      path: path.join(__dirname, '../../../charts/metrics-server/'),
    });
    chart_asset.grantRead(props.helmDeployRole);

    this.metricsServerChart = props.cluster.addHelmChart('MetricsServer', {
      release: 'metrics-server',
      chartAsset: chart_asset,
      namespace: 'kube-system',
      wait: true,
      values: {
        nodeSelector: { 'app/voicebot': 'enabled' },
      },
      timeout: Duration.minutes(10),
    });
  }
}