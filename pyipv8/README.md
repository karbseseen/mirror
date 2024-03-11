**FAQ:**

- **Q:** Is this the new official Layer 3 solution for the Internet?
- **A:** No, the naming is a [10-years-old](https://www.tribler.org/IPv8/) mockery of the deployment failure of IPv6 (which we sincerely hope will be deployed properly at some point in time).

**Linux**: [![](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_linux/badge/icon)](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_linux/) **Windows**: [![](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_windows/badge/icon)](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_windows/) **Mac**: [![](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_mac/badge/icon)](http://jenkins-ci.tribler.org/job/ipv8/job/test_ipv8_mac/)

**Mutation Tests**: [![](https://jenkins-ci.tribler.org/job/ipv8/job/mutation_test_daily/badge/icon)](https://jenkins-ci.tribler.org/job/ipv8/job/mutation_test_daily/HTML_20Report/)

**Read the Docs**: [![](https://readthedocs.org/projects/py-ipv8/badge/?version=latest)](https://py-ipv8.readthedocs.io/)

## What is IPv8 ?

IPv8 aims to provide authenticated communication with privacy.
The design principle is to enable communication between public key pairs: IP addresses and physical network attachment points are abstracted away.
This Python 3 package is an amalgamation of peer-to-peer communication functionality from [Dispersy](https://github.com/Tribler/dispersy) and [Tribler](https://github.com/Tribler/tribler), developed over the last 18 years by students and employees of the Delft University of Technology.
The IPv8 library allows you to easily create network overlays on which to build your own applications.

### IPv8 Objectives

- **Authentication**. We offer mutual authentication using strong cryptography. During an IPv8 communication session, both parties can be sure of the other party’s identity. IPv8 users are identified by their public key. The initial key exchange is designed so that secrets are never transmitted across the Internet, not even in encrypted form. We use a standard challenge/response protocol with protection against spoofing, man-in-the-middle, and replay attacks.
- **Privacy**. IPv8 is specifically designed for strong privacy protection and end-to-end encryption with perfect forward secrecy. We enhanced the industry standard onion routing protocol, Tor, for usage in a trustless environment (e.g. no trusted central directory servers).
- **No infrastructure dependency**. Everybody is equal in the world of IPv8. No central web server, discovery server, or support foundation is needed.
- **Universal connectivity**. IPv8 can establish direct communication in difficult network situations. This includes connecting people behind a NAT or firewall.   IPv8 includes a single simple and effective NAT traversal technique: UDP hole-punching. This is essential when offering privacy without infrastructure and consumer-grade donated resources.
- **Trust**. You can enhance your security if you tell IPv8 which people you know and trust. It tries to build a web-of-trust automatically.

### Dependencies
The dependencies for IPv8 are collected in the `requirements.txt` file and can be installed using `pip`:

```
python3 -m pip install --upgrade -r requirements.txt
```

On Windows or MacOS you will need to install `Libsodium` separately, as explained [here](https://github.com/Tribler/py-ipv8/blob/master/doc/preliminaries/install_libsodium.rst). 

### Tests
Running the test suite requires the installation of `asynctest` (`python3 -m pip install asynctest`).
Running tests can be done by running:

```
python3 run_all_tests.py
```

Running code coverage requires the `coverage` package (`python3 -m pip install coverage`).
A coverage report can be generated by running:

```
python3 create_test_coverage_report.py
```

### Getting started
You can start creating your first network overlay by following [the overlay creation tutorial](https://py-ipv8.readthedocs.io/en/latest/basics/overlay_tutorial.html).

We provide additional documentation on [configuration](https://py-ipv8.readthedocs.io/en/latest/reference/configuration.html), [key generation](https://py-ipv8.readthedocs.io/en/latest/reference/keys.html) and [message serialization formats](https://py-ipv8.readthedocs.io/en/latest/reference/serialization.html) on [our ReadTheDocs page](https://py-ipv8.readthedocs.io/en/latest/).