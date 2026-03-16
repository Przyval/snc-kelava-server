#!/usr/bin/env python3
"""
KIL Web Routes
==============
Serves HTML dashboards for Ops Intelligence.
"""

import asyncio
from datetime import date

import httpx
from flask import Blueprint, current_app, render_template

web_bp = Blueprint("web", __name__, template_folder="templates", static_folder="static")


def get_api_data(endpoint):
    """Helper to fetch data from local API"""
    # In a real app we might call internal service logic directly,
    # but consuming our own API ensures strict separation.
    # For simplicity in Flask, we can also just import the service functions.
    # Here we'll just use internal requests to simulate consumption.
    port = current_app.config.get("PORT", 5001)
    url = f"http://localhost:{port}/api/v1/{endpoint}"
    try:
        response = httpx.get(url)
        return response.json()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


@web_bp.route("/")
def dashboard():
    """Redirect to Enterprise Dashboard"""
    from flask import redirect, url_for

    return redirect("/enterprise")


@web_bp.route("/m")
@web_bp.route("/m/")
def mobile_web():
    """Mobile web app — browser-based field service interface."""
    return render_template("enterprise/mobile.html")
