# -*- coding: utf-8 -*-

"""Main module. Launch by running python -m rest_uploader.cli"""

import os
import shutil
import tempfile
import platform
import time
import mimetypes
import json
import requests
import csv
from tabulate import tabulate
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from img_processor2 import ImageProcessor
from api_token import get_token_suffix
from pathlib import Path


"""
2018-09-24 JRK
This program was created to upload files from a folder specified in the
PATH variable to Joplin. The following resource was helpful in figuring out
the logic for Watchdog:
https://stackoverflow.com/questions/18599339/python-watchdog-monitoring-file-for-changes

Tested with the following extensions:
.md
.txt
.pdf
.png
.jpg
.url

Caveat
Uploader only triggered upon new file creation, not modification
"""


class MyHandler(FileSystemEventHandler):
    def _event_handler(self, path):
        filename, ext = os.path.splitext(path)
        if ext not in (".tmp", ".part", ".crdownload") and ext[:2] not in (".~"):
            filesize = self.valid_file(ext, path)
            if filesize > MAX_UPLOAD_FILE_SIZE:   # was 10000000
                print(f"Filesize = {filesize}. Maybe too big for Joplin, skipping upload")
                return False
            else:
                i = 1
                max_retries = 5
                while i <= max_retries:
                    if i > 1:
                        print(f"Retrying file upload {i} of {max_retries}...")
                    if upload(path) < 0:
                        time.sleep(5)
                    else:
                        return True
                print(f"Tried {max_retries} times but failed to upload file {path}")
                return False
        else:
            print("Detected temp file. Temp files are ignored.")

    def valid_file(self, ext, path):
        """Ensure file is completely written before processing"""
        size_past = -1
        while True:
            size_now = os.path.getsize(path)
            if size_now == size_past:
                print(f"File xfer complete. Size={size_now}")
                return size_now
            else:
                size_past = os.path.getsize(path)
                print(f"File transferring...{size_now}")
                time.sleep(1)
        return -1

    def on_created(self, event):
        print(event.event_type + " -- " + event.src_path)
        self._event_handler(event.src_path)

    def on_moved(self, event):
        print(event.event_type + " -- " + event.dest_path)
        self._event_handler(event.dest_path)


def set_working_directory():
    """Set working directory"""
    if os.getcwd() != os.chdir(os.path.dirname(os.path.realpath(__file__))):
        os.chdir(os.path.dirname(os.path.realpath(__file__)))


def set_language(language):
    global LANGUAGE
    LANGUAGE = language


def set_max_upload_file_size(max_upload_file_size):
    """was 10000000 in early versions of joplin, limit has been removed sice and is now mainly for compatibility with older android devices and or encryption """
    global MAX_UPLOAD_FILE_SIZE
    MAX_UPLOAD_FILE_SIZE = max_upload_file_size


def set_token():
    global TOKEN
    TOKEN = get_token_suffix()


def set_autotag(autotag):
    global AUTOTAG
    AUTOTAG = True
    if autotag == "no":
        AUTOTAG = False


def set_endpoint(server, port):
    global ENDPOINT
    ENDPOINT = f"http://{server}:{port}"
    print(f"Endpoint: {ENDPOINT}")


def set_autorotation(autorotation):
    global AUTOROTATION
    AUTOROTATION = True
    if autorotation == "no":
        AUTOROTATION = False


def set_moveto(moveto):
    global MOVETO
    if moveto == tempfile.gettempdir():
        moveto = ""
    MOVETO = moveto
    return MOVETO


def initialize_notebook(notebook_name):
    global NOTEBOOK_NAME
    NOTEBOOK_NAME = notebook_name
    global NOTEBOOK_ID
    NOTEBOOK_ID = ""
    return NOTEBOOK_NAME


def set_notebook_id(notebook_name=None):
    """ Find the ID of the destination folder 
    adapted logic from jhf2442 on Joplin forum
    https://discourse.joplin.cozic.net/t/import-txt-files/692
    """
    global NOTEBOOK_NAME
    global NOTEBOOK_ID
    if notebook_name is not None:
        NOTEBOOK_NAME = initialize_notebook(notebook_name)
    try:
        res = requests.get(ENDPOINT + "/folders" + TOKEN)
        folders = res.json()["items"]
        for folder in folders:
            if folder.get("title") == NOTEBOOK_NAME:
                NOTEBOOK_ID = folder.get("id")
        if NOTEBOOK_ID == "":
            for folder in folders:
                if "children" in folder:
                    for child in folder.get("children"):
                        if child.get("title") == NOTEBOOK_NAME:
                            NOTEBOOK_ID = child.get("id")
        return NOTEBOOK_ID
    except requests.ConnectionError as e:
        print("Connection Error - Is Joplin Running?")
        return "err"


def read_text_note(filename):
    with open(filename, "r") as myfile:
        text = myfile.read()
        print(text)
    return text


def read_csv(filename):
    return csv.DictReader(open(filename))


def apply_tags(text_to_match, note_id):
    """ Rudimentary Tag match using OCR'd text """
    res = requests.get(ENDPOINT + "/tags" + TOKEN)
    tags = res.json()["items"]
    counter = 0
    for tag in tags:
        if tag.get("title").lower() in text_to_match.lower():
            counter += 1
            tag_id = tag.get("id")
            response = requests.post(
                ENDPOINT + f"/tags/{tag_id}/notes" + TOKEN,
                data=f'{{"id": "{note_id}"}}',
            )
    print(f"Matched {counter} tag(s) for note {note_id}")
    return counter


def create_resource(filename):
    if NOTEBOOK_ID == "":
        set_notebook_id()
    basefile = os.path.basename(filename)
    title = os.path.splitext(basefile)[0]
    files = {
        "data": (json.dumps(filename), open(filename, "rb")),
        "props": (None, f'{{"title":"{title}", "filename":"{basefile}"}}'),
    }
    response = requests.post(ENDPOINT + "/resources" + TOKEN, files=files)
    return response.json()


def delete_resource(resource_id):
    apitext = ENDPOINT + "/resources/" + resource_id + TOKEN
    response = requests.delete(apitext)
    return response


def get_resource(resource_id):
    apitext = ENDPOINT + "/resources/" + resource_id + TOKEN
    response = requests.get(apitext)
    return response


def set_json_string(title, NOTEBOOK_ID, body, img=None):
    if img is None:
        return '{{ "title": {}, "parent_id": "{}", "body": {} }}'.format(
            json.dumps(title), NOTEBOOK_ID, json.dumps(body)
        )
    else:
        return '{{ "title": "{}", "parent_id": "{}", "body": {}, "image_data_url": "{}" }}'.format(
            title, NOTEBOOK_ID, json.dumps(body), img
        )


def upload(filename):
    """ Get the default Notebook ID and process the passed in file"""
    basefile = os.path.basename(filename)
    title, ext = os.path.splitext(basefile)
    body = f"{basefile} uploaded from {platform.node()}\n"
    datatype = mimetypes.guess_type(filename)[0]
    if datatype is None:
        # avoid subscript exception if datatype is None
        if ext in (".url", ".lnk"):
            datatype = "text/plain"
        else:
            datatype = ""
    if datatype == "text/plain":
        body += read_text_note(filename)
        values = set_json_string(title, NOTEBOOK_ID, body)
    if datatype == "text/csv":
        table = read_csv(filename)
        body += tabulate(table, headers="keys", numalign="right", tablefmt="pipe")
        values = set_json_string(title, NOTEBOOK_ID, body)
    elif datatype[:5] == "image":
        img_processor = ImageProcessor(LANGUAGE)
        body += "\n<!---\n"
        try:
            body += img_processor.extract_text_from_image(filename, autorotate=AUTOROTATION)
        except TypeError:
            print("Unable to perform OCR on this file.")
        except OSError:
            print(f"Invalid or incomplete file - {filename}")
            return -1
        body += "\n-->\n"
        img = img_processor.encode_image(filename, datatype)
        del img_processor
        values = set_json_string(title, NOTEBOOK_ID, body, img)
    else:
        response = create_resource(filename)
        body += f"[{basefile}](:/{response['id']})"
        values = set_json_string(title, NOTEBOOK_ID, body)
        if response["file_extension"] == "pdf":
            img_processor = ImageProcessor(LANGUAGE)
            if img_processor.pdf_valid(filename):
                # Special handling for PDFs
                body += "\n<!---\n"
                body += img_processor.extract_text_from_pdf(filename)
                body += "\n-->\n"
                previewfile = img_processor.PREVIEWFILE
                if not os.path.exists(previewfile):
                    previewfile = img_processor.pdf_page_to_image(filename)
                img = img_processor.encode_image(previewfile, "image/png")
                del img_processor
                os.remove(previewfile)
                values = set_json_string(title, NOTEBOOK_ID, body, img)

    headers = {'Content-type': 'application/x-www-form-urlencoded; charset=utf-8'}
    response = requests.post(ENDPOINT + "/notes" + TOKEN, data=values.encode('utf-8'), headers=headers)
    #response = requests.post(ENDPOINT + "/notes" + TOKEN, data=values) old without utf-8 therefore no german umlauts like äöü?

    if response.status_code == 200:
        if AUTOTAG:
            apply_tags(body, response.json().get("id"))
        print(f"Placed note into notebook {NOTEBOOK_ID}: {NOTEBOOK_NAME}")
        if os.path.isdir(MOVETO):
            moveto_filename = os.path.join(MOVETO, basefile)
            print(moveto_filename)
            if os.path.exists(moveto_filename):
                print(f"{basefile} exists in moveto dir, not moving!")
            else:
                try:
                    # Give it a few seconds to release file lock
                    time.sleep(5)
                    shutil.move(filename, MOVETO)
                except IOError:
                    print(f"File Locked-unable to move {filename}")
        return 0
    else:
        print("ERROR! NOTE NOT CREATED")
        print("Something went wrong corrupt file or note > max upload file size?")
        return -1


def watcher(path=None):
    if path is None:
        path = str(Path.home())
    event_handler = MyHandler()
    print(f"Monitoring directory: {path}")
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    set_endpoint('127.0.0.1', '41184')
    set_language('deu+eng')
    global TOKEN
    TOKEN = "not-set"
    if os.environ.get('JOPLIN_TOKEN') is not None:
        TOKEN = "?token=" + os.environ['JOPLIN_TOKEN']
    else:
        print("Please set the environment variable JOPLIN_TOKEN")
        exit(1)
    global MAX_UPLOAD_FILE_SIZE
    MAX_UPLOAD_FILE_SIZE = 100000000
    global NOTEBOOK_ID
    destination = "inbox"
    NOTEBOOK_ID = set_notebook_id(destination.strip())
    global AUTOTAG
    AUTOTAG = False
    global AUTOROTATION
    AUTOROTATION = True
    
    global MOVETO
    moveto = """B:/Temp/restuploadertest"""
    if moveto == tempfile.gettempdir():
        moveto = ""
    MOVETO = moveto

    watcher()
