#!/bin/bash

set -o errexit
set -o verbose

# Install local CDK CLI version
npx npm install

# Install project dependencies
pip install -r requirements.txt -r requirements-dev.txt


#mypy --install-types
