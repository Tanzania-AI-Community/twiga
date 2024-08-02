# webhook.py
import os
from fastapi import FastAPI, Request, Response
from app.whatsapp_service import WhatsAppWrapper
import logging

app = FastAPI()
