blurb_it
--------

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black

.. image:: https://github.com/python/blurb_it/actions/workflows/ci.yml/badge.svg?event=push
    :target: https://github.com/python/blurb_it/actions

.. image:: https://codecov.io/gh/python/blurb_it/branch/main/graph/badge.svg
    :target: https://codecov.io/gh/python/blurb_it

``blurb add`` over the internet.

About
=====

📜🤖 blurb-it allows you to add a misc/news file to your own
`CPython <https://github.com/python/cpython>`_ pull request.

A ``Misc/NEWS.d`` file `is needed
<https://devguide.python.org/core-developers/committing/index.html#updating-news-and-what-s-new-in-python>`_
for almost all non-trivial changes to CPython.

To use blurb-it, you must be logged in to GitHub.

Install blurb-it GitHub App to your account, and then grant the ``write`` access to your
fork of the CPython repository.

Since blurb-it will have write access to the granted repo, you should only install
it on your own CPython repository.

`Install blurb-it <https://github.com/apps/blurb-it/installations/new>`_ .

Uninstall blurb-it
==================

1. Go to https://github.com/settings/installations.

2. Click blurb-it's "Configure" button.

3. Scroll down and click the "Uninstall" button.

Deploy
======

|Deploy|

.. |Deploy| image:: https://www.herokucdn.com/deploy/button.svg
   :target: https://heroku.com/deploy?template=https://github.com/python/blurb_it


Requirements and dependencies
=============================

- Python 3.11+
- aiohttp
- aiohttp-jinja2
- gidgethub >= 5.0.0
- pyjwt >= 2.0.0
- cryptography


Running tests
=============

1. Create a Python virtual environment with ``$ python3 -m venv venv``
2. Activate the virtual environment with ``$ . venv/bin/activate``
3. Install dev requirements with ``(venv)$ pip install -r dev-requirements.txt``
4. Run all tests with ``(venv)$ pytest tests``

Running locally
===============

Prerequisites
-------------

Set up a virtual environment and install the dev dependencies::

   python3 -m venv venv
   . venv/bin/activate
   pip install -r dev-requirements.txt

**macOS only:** if you installed Python from python.org, run the certificate
installer once so that aiohttp can verify SSL connections to GitHub::

   open "/Applications/Python 3.x/Install Certificates.command"

Replace ``3.x`` with your Python version (e.g. ``3.13`` or ``3.14``).

The ``ENV/`` directory is gitignored — create it to store credentials::

   mkdir -p ENV

Create a GitHub App
-------------------

You need a GitHub App so the server can commit blurb files to users' CPython
forks on their behalf.

1. Go to https://github.com/settings/apps/new and fill in:

   - **GitHub App name**: anything unique (e.g. ``blurb-it-yourname-dev``)
   - **Homepage URL**: your fork (e.g. ``https://github.com/<username>/blurb_it``)
   - **Callback URL**: ``http://127.0.0.1:8080``
   - **Setup URL**: ``http://127.0.0.1:8080``
   - **Webhook** → uncheck *Active* (GitHub can't reach localhost)
   - **Repository permissions** → *Contents*: **Read & Write**
   - **Where can this GitHub App be installed?** → *Only on this account*

2. Click **Create GitHub App**.

3. On the app's settings page, note the following — you'll need them for the
   config file:

   - **App ID** — shown near the top of the page
   - **Client ID** — shown in the "OAuth App" section

4. Scroll down and click **Generate a new client secret**. Copy it immediately
   (it is only shown once).

5. Scroll down and click **Generate a private key**. A ``.pem`` file downloads
   automatically — move it into the ``ENV/`` directory::

      mv ~/Downloads/<appname>.*.private-key.pem ENV/

6. In the sidebar click **Install App**, then install it on your CPython fork
   (select *Only select repositories* → your fork of ``python/cpython``).

Configure and run
-----------------

Create ``ENV/localdev.toml``::

   app_url = "127.0.0.1"           # hostname only; port is appended automatically
   github_app_id = "12345"         # App ID from step 3 above
   github_private_key_path = "<appname>.*.private-key.pem"  # filename inside ENV/
   github_client_id = "Iv1.abc123" # Client ID from step 3 above
   github_client_secret = "..."    # secret generated in step 4 above
   port = 8080

Run the app::

   python3 -m blurb_it localdev

Then open http://127.0.0.1:8080 in your browser and sign in with GitHub.
