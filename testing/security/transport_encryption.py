"""
A collection of utilities used for SSL tests.
"""
import json
import logging


import sdk_cmd


log = logging.getLogger(__name__)


def fetch_dcos_ca_bundle(task: str) -> str:
    """Fetch the DC/OS CA bundle from the leading Mesos master"""
    local_bundle_file = "dcos-ca.crt"

    cmd = ["curl", "-L", "--insecure", "-v",
           "leader.mesos/ca/dcos-ca.crt",
           "-o", local_bundle_file]

    sdk_cmd.task_exec(task, " ".join(cmd))

    return local_bundle_file


def create_tls_artifacts(cn: str, task: str) -> str:
    pub_path = "{}_pub.crt".format(cn)
    priv_path = "{}_priv.key".format(cn)
    log.info("Generating certificate. cn={}, task={}".format(cn, task))

    output = sdk_cmd.task_exec(
        task,
        'openssl req -nodes -newkey rsa:2048 -keyout {} -out request.csr '
        '-subj "/C=US/ST=CA/L=SF/O=Mesosphere/OU=Mesosphere/CN={}"'.format(priv_path, cn))
    log.info(output)
    assert output[0] is 0

    rc, raw_csr, _ = sdk_cmd.task_exec(task, 'cat request.csr')
    assert rc is 0
    request = {
        "certificate_request": raw_csr
    }

    token = sdk_cmd.run_cli("config show core.dcos_acs_token")

    output = sdk_cmd.task_exec(
        task,
        "curl --insecure -L -X POST "
        "-H 'Authorization: token={}' "
        "leader.mesos/ca/api/v2/sign "
        "-d '{}'".format(token, json.dumps(request)))
    log.info(output)
    assert output[0] is 0

    # Write the public cert to the client
    certificate = json.loads(output[1])["result"]["certificate"]
    output = sdk_cmd.task_exec(task, "bash -c \"echo '{}' > {}\"".format(certificate, pub_path))
    log.info(output)
    assert output[0] is 0

    create_keystore_truststore(cn, task)
    return "CN={},OU=Mesosphere,O=Mesosphere,L=SF,ST=CA,C=US".format(cn)


def create_keystore_truststore(cn: str, task: str):
    pub_path = "{}_pub.crt".format(cn)
    priv_path = "{}_priv.key".format(cn)
    keystore_path = "{}_keystore.jks".format(cn)
    truststore_path = "{}_truststore.jks".format(cn)

    log.info("Generating keystore and truststore, task:{}".format(task))
    dcos_ca_bundle = fetch_dcos_ca_bundle(task)

    # Convert to a PKCS12 key
    output = sdk_cmd.task_exec(
        task,
        'bash -c "export RANDFILE=/mnt/mesos/sandbox/.rnd && '
        'openssl pkcs12 -export -in {} -inkey {} '
        '-out keypair.p12 -name keypair -passout pass:export '
        '-CAfile {} -caname root"'.format(pub_path, priv_path, dcos_ca_bundle))
    log.info(output)
    assert output[0] is 0

    log.info("Generating certificate: importing into keystore and truststore")
    # Import into the keystore and truststore
    output = sdk_cmd.task_exec(
        task,
        "keytool -importkeystore "
        "-deststorepass changeit -destkeypass changeit -destkeystore {} "
        "-srckeystore keypair.p12 -srcstoretype PKCS12 -srcstorepass export "
        "-alias keypair".format(keystore_path))
    log.info(output)
    assert output[0] is 0

    output = sdk_cmd.task_exec(
        task,
        "keytool -import -trustcacerts -noprompt "
        "-file {} -storepass changeit "
        "-keystore {}".format(dcos_ca_bundle, truststore_path))
    log.info(output)
    assert output[0] is 0
