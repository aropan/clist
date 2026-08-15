#!/usr/bin/env python3

import logging
import os
import random
import re
import string
import subprocess

VARIABLE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")


def random_string(length=40):
    return "".join(random.choices(list(string.ascii_letters + string.digits), k=length))


def create_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def enter_value(variable, old_value):
    if not old_value:
        logger.info(f"Generated new value for {variable} default")
        old_value = random_string()
    if old_value == "{empty}":
        old_value = ""
    value = input(f'Enter {variable} [default "{old_value}"]: ')
    if not value:
        value = old_value
    return value


def get_variable(line):
    match = VARIABLE_RE.match(line)
    return match.group(1) if match else None


def split_template_entries(lines):
    entries = []
    leading_lines = []
    current_variable = None
    current_lines = []

    for line in lines:
        variable = get_variable(line)
        if variable is None:
            if current_variable is None:
                leading_lines.append(line)
            else:
                current_lines.append(line)
            continue

        if current_variable is not None:
            next_leading_lines = []
            while current_lines and (not current_lines[-1].strip() or current_lines[-1].lstrip().startswith("#")):
                next_leading_lines.insert(0, current_lines.pop())
            entries.append((current_variable, current_lines))
            leading_lines = next_leading_lines

        current_variable = variable
        current_lines = [*leading_lines, line]
        leading_lines = []

    if current_variable is not None:
        entries.append((current_variable, current_lines))

    return entries


def render_template(lines, accept_default, allow_empty):
    generated = ""
    n_sep_skip = 0

    for line in lines:
        line = line.rstrip()
        parts = re.split(r"\s*=\s*", line, maxsplit=1)
        if len(parts) < 2:
            generated += f"{line}\n"
            continue

        entry = re.search(r"\s*=\s*", line)
        sep = entry.group(0)

        variable, old_value = parts
        entry = re.search(r"""^['"]""", old_value)
        quote = entry.group(0) if entry else ""
        if old_value.endswith("random-string"):
            old_value = ""
        if old_value and " " in sep:
            n_sep_skip += 1
            generated += f"{line}\n"
            continue
        if accept_default and (allow_empty or old_value):
            value = old_value
            logger.info(f'Accept default value "{old_value}" for "{variable}"')
        else:
            value = enter_value(variable, old_value)
        generated += f"{variable}{sep}{quote}{value}{quote}\n"

    return generated, n_sep_skip


def fill_template(target_file, accept_default=False, allow_empty=False):
    template_file = target_file + ".template"
    with open(template_file) as fo:
        template_lines = fo.readlines()

    target_exists = os.path.exists(target_file)
    target_lines = []
    if target_exists:
        with open(target_file) as fo:
            target_lines = fo.readlines()
        existing_variables = {variable for line in target_lines if (variable := get_variable(line))}
        missing_entries = [
            (variable, lines)
            for variable, lines in split_template_entries(template_lines)
            if variable not in existing_variables
        ]
        if not missing_entries:
            logger.info(f"File {target_file} already contains all template variables")
            return

        template_lines = []
        for _, lines in missing_entries:
            template_lines.extend(lines)
        missing_variables = ", ".join(variable for variable, _ in missing_entries)
        logger.info(f"Adding missing variables to {target_file}: {missing_variables}")
    else:
        logger.info(f"Generating {target_file}...")

    generated, n_sep_skip = render_template(template_lines, accept_default, allow_empty)
    if target_lines and not target_lines[-1].endswith("\n"):
        generated = "\n" + generated

    mode = "a" if target_exists else "w"
    with open(target_file, mode) as fo:
        fo.write(generated)

    if n_sep_skip:
        logger.warning(f"Please fill other field in {target_file} if needed")


def run_command(cmd):
    cmd = cmd.replace("\n", " ")
    not_sensitive_data = re.sub(r'"[^"]*"', "***", cmd)
    logger.info(f"Run command = {not_sensitive_data}")
    subprocess.run(cmd, shell=True, check=True)


def create_volumes():
    with open("docker-compose.yml") as fo:
        content = fo.read()
    folders = re.findall(r"^\s*device:\s*(.*)", content, re.MULTILINE)
    for folder in folders:
        if not os.path.exists(folder):
            logger.info(f"Creating volume {folder}")
            os.makedirs(folder)


def main():
    fill_template(".env.db")
    fill_template(".env.netdata", accept_default=True, allow_empty=True)
    fill_template(".env.monitoring", accept_default=True, allow_empty=True)
    fill_template(".env.bugsink", accept_default=True, allow_empty=True)
    fill_template(".env.healthchecks", accept_default=True, allow_empty=True)
    fill_template(".env.grafana", accept_default=True, allow_empty=True)
    fill_template("src/.env.dev", accept_default=True)
    fill_template("src/.env.prod", accept_default=True)
    fill_template("src/pyclist/conf.py")
    create_volumes()
    run_command("docker compose build dev")
    run_command("docker compose up --build --detach db")
    run_command("docker compose run dev ./manage.py migrate contenttypes")
    run_command("docker compose run dev ./manage.py migrate auth")
    run_command("docker compose run dev ./manage.py migrate")

    username = enter_value("username", os.getlogin())
    password = enter_value("password", random_string(10))
    email = enter_value("email", "admin@localhost")
    run_command(f'''
        docker compose run dev ./manage.py createadmin
        --username "{username}"
        --password "{password}"
        --email "{email}"
        --noinput
    ''')


logger = create_logger()


if __name__ == "__main__":
    main()
