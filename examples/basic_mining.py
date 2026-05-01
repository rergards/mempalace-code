#!/usr/bin/env python3
"""Example: mine a project folder into the palace."""

import sys

project_dir = sys.argv[1] if len(sys.argv) > 1 else "~/projects/my_app"
print("Step 1: Initialize rooms from folder structure")
print(f"  mempalace-code init {project_dir}")
print("\nStep 2: Mine everything")
print(f"  mempalace-code mine {project_dir}")
print("\nStep 3: Search")
print("  mempalace-code search 'why did we choose this approach'")
