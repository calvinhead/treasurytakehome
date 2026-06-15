---
title: Ttb Label Verifier
emoji: 🌖
colorFrom: pink
colorTo: gray
sdk: gradio
sdk_version: 6.18.0
python_version: '3.13'
app_file: app.py
pinned: false
license: mit
short_description: label verifier
---

# TTB Label Verifier

A prototype web app that verifies an alcohol-beverage label image against the
expected values from its application, flagging mismatches for a compliance agent.

Built as a take-home for a TTB / U.S. Treasury AI Engineer role.

## Status

Early scaffold; deployment smoke test in progress. Core verification logic,
vision-based field extraction, and the verification UI are under construction.

## Setup (local)

    python3.13 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    python app.py

Then open the local URL Gradio prints (usually http://127.0.0.1:7860).

## Live demo

https://huggingface.co/spaces/calvinhead/ttb-label-verifier
