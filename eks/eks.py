import builtins
import typing
from typing import cast

import requests
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_eks as eks
from aws_cdk import aws_iam as iam
from aws_cdk import core as cdk


class EKSEnvironmentProps(cdk.StackProps):

    def __init__(
            self,
            cdk_env: cdk.Environment = None,
            env_name: typing.Optional[builtins.str] = "eks-env",
            cluster_name: typing.Optional[builtins.str] = "eks",
            flux_config_repo_name: typing.Optional[builtins.str] = "flux-eks-gitops-config",
            flux_config_branch_name: typing.Optional[builtins.str] = "eks-multi-env",
            create_spot_nodegroup: typing.Optional[builtins.bool] = False,
            create_arm_nodegroup: typing.Optional[builtins.bool] = False,
            deploy_cluster_autoscaler: typing.Optional[builtins.bool] = True,
            deploy_aws_lb_controller: typing.Optional[builtins.bool] = True,
    ) -> None:
        """Initialization props for EKSEnvironment.

        :param cdk_env: The cdk environment used to Default: - None.
        :param env_name: Environment Name Default: - "eks-env".
        :param cluster_name: EKS cluster name Default: - "eks".
        :param flux_config_repo_name: Flux repository name Default: - "flux-eks-gitops-config".
        :param flux_config_branch_name: Flux repository branch name for manifests Default: - "eks-multi-env".
        :param create_spot_nodegroup: Create Spot instances node group. Default: - False.
        :param create_arm_nodegroup: Create Arm based instances node group. Default: - False.
        :param deploy_cluster_autoscaler: Deploy Cluster Autoscaler add-on. Default: - True.
        :param deploy_aws_lb_controller: Deploy AWS Load Balancer Controller add-on. Default: - True.
        """
        super().__init__()

        self.cdk_env = cdk_env
        self.env_name = env_name
        self.cluster_name = cluster_name
        self.flux_config_repo_name = flux_config_repo_name
        self.flux_config_branch_name = flux_config_branch_name
        self.create_spot_nodegroup = create_spot_nodegroup
        self.create_arm_nodegroup = create_arm_nodegroup
        self.deploy_cluster_autoscaler = deploy_cluster_autoscaler
        self.deploy_aws_lb_controller = deploy_aws_lb_controller


class EKSEnvironment(cdk.Construct):
    def __init__(
            self,
            scope: cdk.Construct,
            id: str,
            vpc: ec2.Vpc,
            eks_environment_props: EKSEnvironmentProps,

    ):
        super().__init__(scope, id)

        self.eks_environment_props = eks_environment_props

        self.vpc = vpc

        self.eks_cluster = self._create_eks()
        self._create_nodegroups()
        self._deploy_addons()

    def _create_eks(self) -> eks.Cluster:

        # Create IAM Role For EC2 bastion instance to be able to manage the cluster
        self.cluster_admin_role = iam.Role(self, "ClusterAdminRole",
                                           assumed_by=cast(
                                               iam.IPrincipal,
                                               iam.CompositePrincipal(
                                                   iam.AccountRootPrincipal(),
                                                   iam.ServicePrincipal(
                                                       "ec2.amazonaws.com")
                                               )
                                           )
                                           )

        cluster_admin_policy_statement = {
            "Effect": "Allow",
            "Action": [
                "eks:DescribeCluster"
            ],
            "Resource": "arn:aws:eks:{region}:{account}:cluster/{cluster_name}-{cluster_env_name}".format(
                region=self.eks_environment_props.cdk_env.region,
                account=self.eks_environment_props.cdk_env.account,
                cluster_name=self.eks_environment_props.cluster_name,
                cluster_env_name=self.eks_environment_props.env_name,
            )
        }
        self.cluster_admin_role.add_to_policy(
            iam.PolicyStatement.from_json(cluster_admin_policy_statement))

        # Create SecurityGroup for the Control Plane ENIs
        eks_security_group = ec2.SecurityGroup(
            self,
            "EKSSecurityGroup",
            vpc=cast(ec2.IVpc, self.vpc),
            allow_all_outbound=True,
        )

        eks_security_group.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.all_traffic()
        )
        # Create an EKS Cluster
        eks_cluster = eks.Cluster(
            self,
            "cluster",
            cluster_name=self.eks_environment_props.cluster_name +
            "-" + self.eks_environment_props.env_name,
            vpc=cast(ec2.IVpc, self.vpc),
            # Use /28 subnets for the Control plane cross account ENIs
            # as recommended in https://docs.aws.amazon.com/eks/latest/userguide/network_reqs.html
            vpc_subnets=[ec2.SubnetSelection(
                subnet_group_name="eks-control-plane")],
            masters_role=cast(iam.IRole, self.cluster_admin_role),
            default_capacity=0,
            security_group=cast(ec2.ISecurityGroup, eks_security_group),
            endpoint_access=eks.EndpointAccess.PRIVATE,
            version=eks.KubernetesVersion.V1_21,
        )

        return eks_cluster

    def _create_nodegroups(self) -> None:

        required_nodegroup_managed_policy = [
            iam.ManagedPolicy.from_aws_managed_policy_name(
                managed_policy_name="AmazonSSMManagedInstanceCore"),
            iam.ManagedPolicy.from_aws_managed_policy_name(
                managed_policy_name="AmazonEKSWorkerNodePolicy"),
            iam.ManagedPolicy.from_aws_managed_policy_name(
                managed_policy_name="AmazonEKS_CNI_Policy"),
            iam.ManagedPolicy.from_aws_managed_policy_name(
                managed_policy_name="AmazonEC2ContainerRegistryReadOnly"),
        ]
        # Create IAM Role For node groups
        od_default_ng_role = iam.Role(self, "ODDefaultNGRole",
                                      assumed_by=cast(
                                          iam.IPrincipal,
                                          iam.CompositePrincipal(
                                              iam.AccountRootPrincipal(),
                                              iam.ServicePrincipal(
                                                  "ec2.amazonaws.com")
                                          )
                                      ),
                                      managed_policies=required_nodegroup_managed_policy,
                                      )

        # On Demand subnets nodegroup
        self.eks_cluster.add_nodegroup_capacity(
            "ODDefaultNodegroup",
            nodegroup_name="od-default-ng",
            capacity_type=eks.CapacityType.ON_DEMAND,
            min_size=0,
            desired_size=1,
            max_size=10,
            ami_type=eks.NodegroupAmiType.AL2_X86_64,
            instance_types=[
                ec2.InstanceType("m5.large"),
            ],
            node_role=od_default_ng_role,
            subnets=ec2.SubnetSelection(subnet_group_name="Private")
        )

        if self.eks_environment_props.create_spot_nodegroup:
            spot_default_ng_role = iam.Role(self, "SPOTDefaultNGRole",
                                            assumed_by=cast(
                                                iam.IPrincipal,
                                                iam.CompositePrincipal(
                                                    iam.AccountRootPrincipal(),
                                                    iam.ServicePrincipal(
                                                        "ec2.amazonaws.com")
                                                )
                                            ),
                                            managed_policies=required_nodegroup_managed_policy,
                                            )

            # Spot subnets nodegroup
            self.eks_cluster.add_nodegroup_capacity(
                "SpotDefaultNodegroup",
                nodegroup_name="spot-default-ng",
                capacity_type=eks.CapacityType.SPOT,
                min_size=0,
                desired_size=1,
                max_size=10,
                ami_type=eks.NodegroupAmiType.AL2_X86_64,
                instance_types=[
                    ec2.InstanceType("m5.large"),
                    ec2.InstanceType("c5.large"),
                    ec2.InstanceType("m4.large"),
                    ec2.InstanceType("c4.large"),
                ],
                node_role=spot_default_ng_role,
                subnets=ec2.SubnetSelection(subnet_group_name="Private")
            )

        if self.eks_environment_props.create_arm_nodegroup:
            od_graviton_ng_role = iam.Role(self, "ODGravitonNGRole",
                                           assumed_by=cast(
                                               iam.IPrincipal,
                                               iam.CompositePrincipal(
                                                   iam.AccountRootPrincipal(),
                                                   iam.ServicePrincipal(
                                                       "ec2.amazonaws.com")
                                               )
                                           ),
                                           managed_policies=required_nodegroup_managed_policy,
                                           )
            # Graviton subnets nodegroup
            self.eks_cluster.add_nodegroup_capacity(
                "ODGravitonNodegroup",
                nodegroup_name="od-graviton-ng",
                capacity_type=eks.CapacityType.SPOT,
                min_size=0,
                desired_size=0,
                max_size=10,
                ami_type=eks.NodegroupAmiType.AL2_ARM_64,
                instance_types=[
                    ec2.InstanceType("m6g.large"),
                ],
                node_role=od_graviton_ng_role,
                subnets=ec2.SubnetSelection(subnet_group_name="Private")
            )

    def _create_fargate_profile(self) -> None:
        self.eks_cluster.add_fargate_profile(
            "DefaultFargateProfile",
            selectors=[eks.Selector(
                namespace="default",
                labels={"fargate": "enabled"}
            )],
            fargate_profile_name="default-fp",
            subnet_selection=ec2.SubnetSelection(subnet_group_name="Private")
        )

    def _deploy_addons(self) -> None:

        self._deploy_bastion()

        if self.eks_environment_props.deploy_cluster_autoscaler:
            self._deploy_cluster_autoscaler()

        if self.eks_environment_props.deploy_aws_lb_controller:
            self._deploy_aws_load_balancer_controller()

    def _deploy_cluster_autoscaler(self) -> None:
        ca_sa_name = "cluster-autoscaler"
        cluster_autoscaler_service_account = self.eks_cluster.add_service_account(
            "cluster_autoscaler",
            name=ca_sa_name,
            namespace="kube-system"
        )
        # Create the PolicyStatements to attach to the role
        cluster_autoscaler_policy_statement = {
            "Effect": "Allow",
            "Action": [
                "autoscaling:DescribeAutoScalingGroups",
                "autoscaling:DescribeAutoScalingInstances",
                "autoscaling:DescribeLaunchConfigurations",
                "autoscaling:DescribeTags",
                "autoscaling:SetDesiredCapacity",
                "autoscaling:TerminateInstanceInAutoScalingGroup",
                "ec2:DescribeLaunchTemplateVersions"
            ],
            "Resource": "*"
        }

        # Attach the necessary permissions
        cluster_autoscaler_service_account.add_to_principal_policy(
            iam.PolicyStatement.from_json(cluster_autoscaler_policy_statement))

        # Install the Cluster Autoscaler
        # For more info see https://github.com/kubernetes/autoscaler
        cluster_autoscaler_chart = self.eks_cluster.add_helm_chart(
            "cluster-autoscaler",
            chart="cluster-autoscaler",
            version="9.9.2",
            release="cluster-autoscaler",
            repository="https://kubernetes.github.io/autoscaler",
            namespace="kube-system",
            values={
                "autoDiscovery": {
                    "clusterName": self.eks_cluster.cluster_name
                },
                "awsRegion": self.eks_environment_props.cdk_env.region,
                "resources": {
                    "requests": {
                        "cpu": "1",
                        "memory": "512Mi",
                    },
                    "limits": {
                        "cpu": "1",
                        "memory": "512Mi",
                    }
                },
                "rbac": {
                    "serviceAccount": {
                        "create": False,
                        "name": ca_sa_name
                    }
                },
                "replicaCount": 1
            }
        )
        cluster_autoscaler_chart.node.add_dependency(self.eks_cluster)

    def _deploy_aws_load_balancer_controller(self):
        aws_lb_controller_name = "aws-load-balancer-controller"

        aws_lb_controller_service_account = self.eks_cluster.add_service_account(
            "aws-load-balancer-controller",
            name=aws_lb_controller_name,
            namespace="kube-system"
        )
        resp = requests.get(
            "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.2.0/docs/install/"
            "iam_policy.json"
        )
        aws_load_balancer_controller_policy = resp.json()

        for stmt in aws_load_balancer_controller_policy["Statement"]:
            aws_lb_controller_service_account.add_to_principal_policy(
                iam.PolicyStatement.from_json(stmt))

        # Deploy the AWS Load Balancer Controller from the AWS Helm Chart
        # For more info check out https://github.com/aws/eks-charts/tree/master/stable/aws-load-balancer-controller
        aws_lb_controller_chart = self.eks_cluster.add_helm_chart(
            "aws-load-balancer-controller",
            chart="aws-load-balancer-controller",
            version="1.2.3",
            release="aws-lb-controller",
            repository="https://aws.github.io/eks-charts",
            namespace="kube-system",
            values={
                "clusterName": self.eks_cluster.cluster_name,
                "region": self.eks_environment_props.cdk_env.region,
                "vpcId": self.vpc.vpc_id,
                "serviceAccount": {
                    "create": False,
                    "name": aws_lb_controller_name
                },
                "replicaCount": 2
            }
        )
        aws_lb_controller_chart.node.add_dependency(
            aws_lb_controller_service_account)

    def _deploy_bastion(self):
        # Create an Instance Profile for our Admin Role to assume w/EC2
        cluster_admin_role_instance_profile = iam.CfnInstanceProfile(
            self, "ClusterAdminRoleInstanceProfile",
            roles=[self.cluster_admin_role.role_name]
        )
        cluster_admin_role_instance_profile.node.add_dependency(
            self.cluster_admin_role)

        # Another way into our Bastion is via Systems Manager Session Manager
        self.cluster_admin_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))

        # policy to retrieve GitHub secrets from secretsmanager for Flux bootstrap command
        bastion_secrets_manager_policy = {
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": [
                "arn:aws:secretsmanager:{region}:*:secret:github-token*".format(
                    region=self.eks_environment_props.cdk_env.region),
            ],
        }
        bastion_ssm_parameter_policy = {
            "Effect": "Allow",
            "Action": "ssm:GetParameter",
            "Resource": [
                "arn:aws:ssm:{region}:*:parameter/github-user".format(
                    region=self.eks_environment_props.cdk_env.region)],
        }

        self.cluster_admin_role.add_to_policy(
            iam.PolicyStatement.from_json(bastion_secrets_manager_policy))
        self.cluster_admin_role.add_to_policy(
            iam.PolicyStatement.from_json(bastion_ssm_parameter_policy))

        # Get Latest Amazon Linux AMI
        amazon_linux_2 = ec2.MachineImage.latest_amazon_linux(
            generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
            edition=ec2.AmazonLinuxEdition.STANDARD,
            virtualization=ec2.AmazonLinuxVirt.HVM,
            storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE
        )

        # Create SecurityGroup for bastion
        bastion_security_group = ec2.SecurityGroup(
            self, "BastionSecurityGroup",
            vpc=self.vpc,
            allow_all_outbound=True
        )

        # Add a rule to allow our new SG to talk to the EKS control plane
        self.eks_cluster.cluster_security_group.add_ingress_rule(
            bastion_security_group,
            ec2.Port.all_traffic()
        )

        # Create our Bastion EC2 instance running CodeServer

        self.bastion = ec2.Instance(
            self, "EKSBastion",
            instance_type=ec2.InstanceType("t3.large"),
            machine_image=amazon_linux_2,
            role=self.cluster_admin_role,
            vpc=self.vpc,
            instance_name=self.eks_cluster.cluster_name + "-bastion",
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=bastion_security_group,
            block_devices=[ec2.BlockDevice(
                device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(20))]
        )

        # Add UserData
        self.bastion.user_data.add_commands("yum -y install perl-Digest-SHA")
        self.bastion.user_data.add_commands(
            "curl -o kubectl https://amazon-eks.s3.us-west-2.amazonaws.com/1.20.4/2021-04-12/bin/linux/amd64/kubectl")
        self.bastion.user_data.add_commands("chmod +x ./kubectl")
        self.bastion.user_data.add_commands("mv ./kubectl /usr/bin")

        self.bastion.user_data.add_commands(
            "aws eks update-kubeconfig --name " +
            self.eks_cluster.cluster_name +
            " --region " +
            self.eks_environment_props.cdk_env.region)

        self.bastion.user_data.add_commands("PATH=$PATH:/usr/local/bin")
        self.bastion.user_data.add_commands("export KUBECONFIG=~/.kube/config")
        self.bastion.user_data.add_commands(
            "curl -s https://fluxcd.io/install.sh | sudo bash")
        self.bastion.user_data.add_commands(
            "echo 'PATH=$PATH:/usr/local/bin' >> ~/.bash_profile")
        self.bastion.user_data.add_commands(
            "echo '. <(flux completion bash)' >> ~/.bash_profile")
        self.bastion.user_data.add_commands(
            "echo '. <(kubectl completion bash)' >> ~/.bash_profile")

        # bootstrap flux using the bastion user-data
        self.bastion.user_data.add_commands(
            "export GITHUB_TOKEN=$(aws --region {region} secretsmanager get-secret-value --secret-id github-token "
            "--query 'SecretString' --output text)".format(
                region=self.eks_environment_props.cdk_env.region)
        )
        self.bastion.user_data.add_commands(
            "export GITHUB_USER=$(aws --region {region} ssm get-parameter --name github-user "
            "--query 'Parameter.Value' --output text)".format(
                region=self.eks_environment_props.cdk_env.region)
        )
        self.bastion.user_data.add_commands("KUBECONFIG=~/.kube/config flux bootstrap github \
                                                      --owner=$GITHUB_USER \
                                                      --repository={flux_config_repo_name} \
                                                      --branch={flux_config_branch_name} \
                                                      --path=clusters/{cluster_name} \
                                                      --personal".format(
            flux_config_repo_name=self.eks_environment_props.flux_config_repo_name,
            flux_config_branch_name=self.eks_environment_props.flux_config_branch_name,
            cluster_name=self.eks_cluster.cluster_name,
        )
        )

        # Wait to deploy Bastion until cluster is up and we're deploying manifests/charts to it
        # This could be any of the charts/manifests I just picked this one at random
        self.bastion.node.add_dependency(self.eks_cluster)
