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
<https://devguide.python.org/getting-started/pull-request-lifecycle/#news-entry>`_
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

See ``pyproject.toml`` for the supported Python versions and dependencies
(runtime pins live in ``requirements.txt``, which ``pyproject.toml`` reads).
On macOS, the system ``/usr/bin/python3`` is too old; install a newer Python
from python.org, Homebrew or uv.


Running tests
=============

1. Create a virtual environment with Python 3.10 or newer, e.g.
   ``$ python3.13 -m venv venv``
2. Activate the virtual environment with ``$ . venv/bin/activate``
3. Update pip with ``(venv)$ python3 -m pip install --upgrade pip``
4. Install the project and its dev dependency group with
   ``(venv)$ pip install -e . --group dev`` (needs pip 25.1+)
5. Run all tests with ``(venv)$ pytest tests``

Alternatively, run the tests on every supported Python version with ``tox``.

Running locally
===============

Prerequisites
-------------

Set up a virtual environment (with Python 3.10 or newer) and install the dev
dependencies::

   python3.13 -m venv venv
   . venv/bin/activate
   python3 -m pip install --upgrade pip
   pip install -e . --group dev

**macOS only:** if you installed Python from python.org, run the certificate
installer once so that aiohttp can verify SSL connections to GitHub::

   open "/Applications/Python 3.x/Install Certificates.command"

Replace ``3.x`` with your Python version (e.g. ``3.13`` or ``3.14``).

The ``ENV/`` directory is gitignored — create it to store credentials::

   mkdir -p ENV/secrets

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
   automatically — move it to ``ENV/secrets/gh_private_key`` (the file name is
   the setting it provides)::

      mv ~/Downloads/<appname>.*.private-key.pem ENV/secrets/gh_private_key

6. In the sidebar click **Install App**, then install it on your CPython fork
   (select *Only select repositories* → your fork of ``python/cpython``).

Configure and run
-----------------

Create ``ENV/localdev.env``::

   APP_URL=127.0.0.1:8080   # host:port, must match the Callback URL above
   APP_PROTOCOL=http
   PORT=8080
   GH_APP_ID=12345          # App ID from step 3 above
   GH_CLIENT_ID=Iv1.abc123  # Client ID from step 3 above
   GH_CLIENT_SECRET=...     # client secret from step 4 above

Add a session cookie key, so you stay signed in across restarts::

   python3 -c "from cryptography.fernet import Fernet; print('SESSION_SECRET=' + Fernet.generate_key().decode())" >> ENV/localdev.env

Run the app from the repository root::

   python3 -m blurb_it localdev

Then open http://127.0.0.1:8080 in your browser and sign in with GitHub.

``localdev`` is the production command (``python3 -m blurb_it``) plus two
configuration sources: ``ENV/localdev.env`` and ``ENV/secrets/``, where each
file's name is a setting and its contents the value. Unknown keys in
``ENV/localdev.env`` are an error, so typos are caught at startup.

Configuration reference
-----------------------

All settings are environment variables. In ``localdev`` they can also be set
in ``ENV/localdev.env`` or as files in ``ENV/secrets/``; an environment
variable takes precedence over both, which is handy for one-off changes::

   PORT=9000 APP_URL=127.0.0.1:9000 python3 -m blurb_it localdev

===================== ================================================= ==========================
Environment variable  Purpose                                           Default
===================== ================================================= ==========================
``GH_APP_ID``         GitHub App ID
``GH_PRIVATE_KEY``    GitHub App private key (PEM contents)
``GH_CLIENT_ID``      GitHub App OAuth client ID
``GH_CLIENT_SECRET``  GitHub App OAuth client secret
``APP_URL``           Public host (and port) of the app, without scheme
``APP_PROTOCOL``      Scheme used to build links back to the app        ``https``
``SESSION_SECRET``    URL-safe base64 Fernet key for session cookies    random per start
``PORT``              Port to listen on                                 aiohttp default (8080)
``SENTRY_DSN``        Sentry DSN for error reporting                    disabled
===================== ================================================= ==========================
