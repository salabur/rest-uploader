"""Main module."""
import pypdf
from pypdf.errors import PdfReadError
import os
import datetime
import time
import tempfile
import mimetypes
from uuid import uuid4
from PIL import Image, TiffImagePlugin, ImageFont, ImageDraw
from pdf2image.pdf2image import convert_from_path
from pytesseract import image_to_string, TesseractError, image_to_osd, Output
from reportlab.pdfgen import canvas
import base64


class ImageProcessor:
    def __init__(self, language="eng"):
        self.set_language(language)
        self.TEMP_PATH = tempfile.gettempdir()
        self.PREVIEWFILE = ""
        self.PAGE_COUNT = 0

    def _get_tmp_filename(self, suffix=".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
            return fh.name

    def _get_output_filename(self, input_file):
        output_filename = "{}_signed{}".format(
                *os.path.splitext(input_file)
            )
        return output_filename
    
    def _create_sig(self, signature):
        img = Image.new('RGBA', (735, 150))
        draw = ImageDraw.Draw(img)
        sigfont = ImageFont.truetype("fonts/HoneyScript-SemiBold.ttf", 70)
        draw.text((20, 30), signature, (0, 0, 200), font=sigfont)
        outputfile = "signature.png"
        img.save(outputfile, 'PNG')
        return outputfile

    def sign_pdf(self, pdf, signature, text, coords, sigdate=False):
        # for y coord, pass in pixels from top of page, as the logic
        # of c.drawImage measures from the bottom to the top. I don't know why
        page_num, x1, y, width, height = [int(a) for a in coords.split("x")]
        page_num -= 1

        output_filename = self._get_output_filename(pdf)

        pdf_fh = open(pdf, 'rb')
        sig_tmp_fh = None

        pdf = pypdf.PdfFileReader(pdf_fh)
        # Set y1 to pixels from top of page
        y1 = int(pdf.getPage(page_num).mediaBox[3] - y)
        print(pdf.getPage(page_num).mediaBox)
        print(y1)
        writer = pypdf.PdfFileWriter()
        sig_tmp_filename = None

        for i in range(0, pdf.getNumPages()):
            page = pdf.getPage(i)

            if i == page_num:
                # Create PDF for signature
                sig_tmp_filename = self._get_tmp_filename()
                c = canvas.Canvas(sig_tmp_filename, pagesize=page.cropBox)
                c.drawImage(signature, x1, y1, width, height, mask='auto')
                if text != "" and text is not None:
                    c.drawString(x1, y1, text)  # text above signature
                if sigdate:
                    c.drawString(x1, y1 - 32,
                                datetime.datetime.now().strftime("%Y-%m-%d"))
                c.showPage()
                c.save()

                # Merge PDF in to original page
                sig_tmp_fh = open(sig_tmp_filename, 'rb')
                sig_tmp_pdf = pypdf.PdfFileReader(sig_tmp_fh)
                sig_page = sig_tmp_pdf.getPage(0)
                sig_page.mediaBox = page.mediaBox
                page.mergePage(sig_page)

            writer.addPage(page)

        with open(output_filename, 'wb') as fh:
            writer.write(fh)

        for handle in [pdf_fh, sig_tmp_fh]:
            if handle:
                handle.close()
        if sig_tmp_filename:
            os.remove(sig_tmp_filename)
        return output_filename
    
    def sign_image(self, img_file, signature, text):
        img = Image.open(img_file)
        draw = ImageDraw.Draw(img)
        glfont = ImageFont.truetype("fonts/Roboto-Black.ttf", 16)
        sigfont = ImageFont.truetype("fonts/HoneyScript-SemiBold.ttf", 40)
        draw.text((200, 10), signature, (0, 0, 0), font=sigfont)
        draw.text((200, 50), text, (0, 0, 200), font=glfont)
        output_filename = self._get_output_filename(img_file)
        img.save(output_filename)
        return output_filename

    def sign_invoice(self, input_file, sig_name, text):
        filename, file_extension = os.path.splitext(input_file)
        if file_extension.lower() == ".pdf":
            sigfile = self._create_sig(sig_name)
            signed_file = self.sign_pdf(input_file, sigfile, text, "1x125x40x150x40")
        else:
            signed_file = self.sign_image(input_file, sig_name, text)
        return signed_file

    def set_language(self, language):
        self.LANGUAGE = language

    def open_pdf(self, filename):
        try:
            pdfFileObject = open(filename, "rb")
            pdf_reader = pypdf.PdfReader(pdfFileObject, strict=False)
            self.PAGE_COUNT = len(pdf_reader.pages)
            return pdf_reader
        except PdfReadError as e:
            logging.warning(f"Error reading PDF: {str(e)}")
            print("PDF not fully written - no EOF Marker")
            return None
        except ValueError as e:
            logging.warning(f"Error reading PDF - {e.args}")
            print("PDF not fully written - no EOF Marker")
            return None

    def pdf_valid(self, filename):
        if self.open_pdf(filename) is None:
            return False
        else:
            return True

    def pdf_page_to_image(self, path, page_num=0):
        pages = convert_from_path(path, 250)
        if page_num == 0:
            tempfile = f"{self.TEMP_PATH}/preview.png"
            self.PREVIEWFILE = tempfile
        else:
            tempfile = f"{self.TEMP_PATH}/{uuid4()}.png"
        pages[page_num].save(tempfile, "PNG")
        return tempfile

    def pdf_to_pngs(self, path):
        self.open_pdf(path)  # get page count
        filename, ext = os.path.splitext(path)
        pages = convert_from_path(path, 250)
        p = 0
        while p < self.PAGE_COUNT:
            print(p)
            pages[p].save(f"{filename}-page{p+1}", "PNG")
            p += 1
        return 0

    def extract_text_from_pdf(self, filename):
        pdfReader = self.open_pdf(filename)
        text = ""
        for i in range(self.PAGE_COUNT):
            text += f"\n\n***PAGE {i+1} of {self.PAGE_COUNT}*** \n\n"
            page = pdfReader.pages[i]
            embedded_text = page.extract_text()
            # if embedded PDF text is minimal or does not exist,
            # run OCR the images extracted from the PDF
            if len(embedded_text) >= 100:
                text += embedded_text
            else:
                extracted_image = self.pdf_page_to_image(filename, i)
                text += self.extract_text_from_image(extracted_image)
                if extracted_image != f"{self.TEMP_PATH}/preview.png":
                    os.remove(extracted_image)
        return text

    def open_image(self, filename):
        try:
            img = Image.open(filename)
            return img
        except OSError:
            print("Image not fully written")
            return None

    def image_valid(self, filename):
        img = self.open_image(filename)
        if img is None:
            del img
            return False
        else:
            try:
                img.verify()
                del img
            except OSError:
                return False
            # if no exception is thrown, we have a valid image
            return True

    def extract_text_from_image(self, filename, autorotate=True): #TODO reset to False
        try:
            img = self.open_image(filename)
            text = image_to_string(img, lang=self.LANGUAGE)
            rot_data = image_to_osd(filename, output_type=Output.DICT)
            if autorotate:
                degrees_to_rotate = rot_data["orientation"]
                # rotate if text is extracted with reasonable confidence
                if degrees_to_rotate != 0 and rot_data["orientation_conf"] > 2:
                    self.rotate_image(filename, degrees_to_rotate)
                    # need to re-run the OCR after rotating
                    img = Image.open(filename)
                    text = image_to_string(img, lang=self.LANGUAGE)
                    print(f"Rotated image {degrees_to_rotate} degrees")

        except TesseractError as e:
            text = "\nCheck Tesseract OCR Configuration\n"
            text += e.message
        return text

    def encode_image(self, filename, datatype):
        encoded = base64.b64encode(open(filename, "rb").read())
        img = f"data:{datatype};base64,{encoded.decode()}"
        return img

    def rotate_image(self, filename, degrees_counterclockwise):
        im = Image.open(filename)
        angle = degrees_counterclockwise
        out = im.rotate(angle, expand=True)
        # overwrite the file
        out.save(filename)

    def convert_pdf_to_tiff(self, filename, delete_original=False):
        self.open_pdf(filename)
        i = 0
        list_file = []
        basefile = os.path.basename(filename)
        title = os.path.splitext(basefile)[0]
        new_files = []
        while i < self.PAGE_COUNT:
            pages = convert_from_path(filename, 200)
            # Save Cover Sheet as Separate File
            if i == 0:
                new_filename = f"{title}-coversheet.tif"
                pages[i].save(new_filename, "TIFF", compression="jpeg")
                new_files.append(new_filename)

            else:  # Handle remaining pages
                tempfile = f"temp_{title}-{i}.tif"
                list_file.append(tempfile)
                pages[i].save(tempfile, "TIFF", compression="jpeg")
            i += 1
            pages.clear()
        if self.PAGE_COUNT > 1:
            new_filename = f"{title}.tif"
            with TiffImagePlugin.AppendingTiffWriter(new_filename, True) as tf:
                for tiff_in in list_file:
                    try:
                        im = Image.open(tiff_in)
                        im.save(tf)
                        tf.newFrame()
                        im.close()
                    finally:
                        os.remove(tiff_in)  # delete temp file
                        pass
            new_files.append(new_filename)
        print("Conversion complete!")
        if delete_original:
            print("Removing original PDF...")
            os.remove(filename)
            print("Local PDF deleted!")
        return new_files
