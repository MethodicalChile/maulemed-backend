from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
import google.generativeai as genai
import logging
from apps.common.services.chat_context import get_product_context

logger = logging.getLogger(__name__)

class ChatView(APIView):
    def post(self, request):
        user_message = request.data.get('message', '')
        if not user_message:
            return Response({'error': 'No message provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            genai.configure(api_key=settings.API_KEY_GEMINI)
            model_name = 'gemini-3.1-flash-lite'
            
            # Obtener contexto de la BD
            db_context = get_product_context()
            
            system_instruction = f"""
            Eres un asistente virtual amable y profesional de MauleMed. Tu objetivo es ayudar a los usuarios con consultas sobre la plataforma, procesos internos y dudas generales de manera clara y concisa.
            
            Contexto de la base de datos:
            {db_context}
            
            Responde siempre en español basándote en este contexto si es relevante para la pregunta.
            """
            
            model = genai.GenerativeModel(
                model_name,
                system_instruction=system_instruction
            )
            
            # Obtener historial de la petición (si existe)
            history = request.data.get('history', [])
            
            # Convertir historial a formato compatible con Google Generative AI si es necesario
            # A veces el historial enviado desde el frontend requiere ajuste.
            
            chat = model.start_chat(history=history)
            
            response = chat.send_message(user_message)
            
            # Extraer historial serializable
            serializable_history = []
            for message in chat.history:
                serializable_history.append({
                    'role': message.role,
                    'parts': [{'text': part.text} for part in message.parts]
                })
            
            return Response({'response': response.text, 'history': serializable_history})
        except Exception as e:
            logger.error(f"Error in ChatView: {e}")
            return Response({'error': 'Error processing request'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
