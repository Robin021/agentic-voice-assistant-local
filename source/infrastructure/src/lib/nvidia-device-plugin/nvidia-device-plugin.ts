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


export interface NvidiaDevicePluginConstructProps {
  readonly cluster: eks.Cluster;
  readonly helmDeployRole: iam.Role;
}

export class NvidiaDevicePluginConstruct extends Construct {

  readonly nvidiaDevicePluginChart: eks.HelmChart;

  constructor(scope: Construct, id: string, props: NvidiaDevicePluginConstructProps) {
    super(scope, id);


    // Create ALB Load Balancer Controller ServiceAccount
    const chart_asset = new s3_assets.Asset(this, 'NvidiaDevicePluginChartAsset', {
      path: path.join(__dirname, '../../../charts/nvidia-device-plugin/'),
    });
    chart_asset.grantRead(props.helmDeployRole);

    this.nvidiaDevicePluginChart = props.cluster.addHelmChart('NvidiaDevicePlugin', {
      release: 'nvidia-device-plugin',
      chartAsset: chart_asset,
      namespace: 'kube-system',
      wait: true,
      values: {
        config: {
          name: 'nvidia-device-plugin-config',
        },
        nodeSelector: { 'nvidia.com/gpu.present': 'true' },
      },
      timeout: Duration.minutes(10),
    });
  }
}