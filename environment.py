from aws_cdk import core as cdk

from eks.eks import EKSEnvironment
from eks.eks import EKSEnvironmentProps
from network.infra import EKSEnvironmentNetwork


class EKSMultiEnv(cdk.Stage):
    # pylint: disable=redefined-builtin
    # The 'id' parameter name is CDK convention.
    def __init__(
            self,
            scope: cdk.Construct,
            id_: str,
            *,
            env: cdk.Environment,
            outdir: str = None,
            eks_env_props: EKSEnvironmentProps,
    ):
        super().__init__(scope, id_, env=env, outdir=outdir)

        eks_multi_env_network_stack = cdk.Stack(self, "Network")
        network = EKSEnvironmentNetwork(
            eks_multi_env_network_stack,
            "EKSMultiEnvNetwork")

        eks_multi_env_cluster_stack = cdk.Stack(self, "EKS")
        eks_multi_env_cluster_stack.add_dependency(eks_multi_env_network_stack)

        eks_env_props.cdk_env = env
        EKSEnvironment(scope=eks_multi_env_cluster_stack,
                       id="EKSMultiEnvClusterEKS",
                       vpc=network.vpc,
                       eks_environment_props=eks_env_props,
                       )
