import json
import yaml
from jinja2 import Template
from job import Job


class PodTemplate():
    def __init__(self, template, enable_custom_scheduler=False):
        self.template = template
        self.enable_custom_scheduler = enable_custom_scheduler

    def generate_pod(self, pod):
        assert(isinstance(self.template, Template))
        if self.enable_custom_scheduler:
            if "useGPUTopology" in pod and pod["useGPUTopology"]:
                gpu_topology_flag = 1
            else:
                # for cases when desired topology is explictly given or not desired
                gpu_topology_flag = 0
            pod_name = pod["podName"]
            request_gpu = int(pod["resourcegpu"])

            podInfo = {
                "podname": pod_name,
                "requests": {
                    "alpha.gpu/gpu-generate-topology": gpu_topology_flag
                },
                "runningcontainer": {
                    pod_name: {
                        "requests": {"alpha.gpu/numgpu": request_gpu}
                    },
                },
            }

            if "annotations" not in pod:
                pod["annotations"] = {}
            pod["annotations"]["pod.alpha/DeviceInformation"] = "'" + json.dumps(podInfo) + "'"
            # TODO it's not safe to update pod["resourcegpu"]
            pod["resourcegpu"] = 0  # gpu requests specified through annotation

        if "nodeSelector" not in pod:
            pod["nodeSelector"] = {}
        if "gpuType" in pod:
            pod["nodeSelector"]["gpuType"] = pod["gpuType"]

        pod_yaml = self.template.render(job=pod)
        return yaml.load(pod_yaml)

    def generate_pods(self, job):
        """
        Return (pods, errors)
        """

        assert(isinstance(job, Job))
        params = job.params
        if any(required_field not in params for required_field in
                [
                    "jobtrainingtype",
                    "jobName",
                    "jobPath",
                    "workPath",
                    "dataPath",
                    "cmd",
                    "userId",
                    "resourcegpu",
                    "userName",
                ]):
            return None, "Missing required parameters!"

        job.job_path = params["jobPath"]
        job.work_path = params["workPath"]
        job.data_path = params["dataPath"]
        # TODO user's mountpoints first, but should after 'job_path'
        job.add_mountpoints(job.job_path_mountpoint())
        if "mountpoints" in params:
            job.add_mountpoints(params["mountpoints"])
        job.add_mountpoints(job.work_path_mountpoint())
        job.add_mountpoints(job.data_path_mountpoint())

        params["mountpoints"] = job.mountpoints

        local_job_path = job.get_local_job_path()
        script_file = job.generate_launch_script(local_job_path, params["userId"], params["resourcegpu"], params["cmd"])
        luanch_cmd = "[\"bash\", \"/job/%s\"]" % script_file

        params["user_email"] = params["userName"]
        params["homeFolderHostpath"] = job.get_homefolder_hostpath()

        params["pod_ip_range"] = job.get_pod_ip_range()
        params["usefreeflow"] = job.is_freeflow_enabled()

        # assign parameters to generate the pod yaml
        params["LaunchCMD"] = luanch_cmd
        params["jobNameLabel"] = ''.join(e for e in params["jobName"] if e.isalnum())
        params["rest-api"] = job.get_rest_api_url()
        pods = []
        if all(hyper_parameter in params for hyper_parameter in ["hyperparametername", "hyperparameterstartvalue", "hyperparameterendvalue", "hyperparameterstep"]):
            env_name = params["hyperparametername"]
            start = int(params["hyperparameterstartvalue"])
            end = int(params["hyperparameterendvalue"])
            step = int(params["hyperparameterstep"])

            for idx, val in enumerate(range(start, end, step)):
                pod = params.copy()
                pod["podName"] = "{0}-pod-{1}".format(job.job_id, idx)
                pod["envs"] = [{"name": env_name, "value": val}]
                pods.append(pod)
        else:
                pod = params.copy()
                pod["podName"] = job.job_id
                pod["envs"] = []
                pods.append(pod)

        enable_custom_scheduler = job.is_custom_scheduler_enabled()
        pod_template = PodTemplate(job.get_template(), enable_custom_scheduler)

        k8s_pods = []
        for pod in pods:
            k8s_pod = pod_template.generate_pod(pod)
            k8s_pods.append(k8s_pod)
        return k8s_pods, None
