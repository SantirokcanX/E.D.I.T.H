"""Web search and page scraping tools for the AI agent."""

from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS


def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Realiza una búsqueda en internet en tiempo real usando DuckDuckGo.
    
    Args:
        query: Consulta o términos de búsqueda.
        max_results: Cantidad máxima de resultados a devolver (por defecto 5).
        
    Returns:
        Lista de diccionarios con 'title', 'url' y 'snippet'.
    """
    try:
        ddgs = DDGS()
        raw_results = ddgs.text(query, max_results=max_results)
        
        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")
            })
        return results
    except Exception as e:
        return [{"error": f"Error al ejecutar búsqueda: {str(e)}"}]


def read_web_page(url: str, max_chars: int = 4000) -> str:
    """
    Descarga y extrae el contenido de texto principal de una página web.
    
    Args:
        url: La dirección URL completa de la página web.
        max_chars: Límite de caracteres para no saturar el contexto.
        
    Returns:
        Texto legible de la página o mensaje de error.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=12.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return f"No se pudo cargar la página. Código de respuesta HTTP: {resp.status_code}"
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Remover scripts, estilos, cabeceras y pies innecesarios
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
                tag.decompose()
            
            text = soup.get_text(separator="\n")
            # Limpiar líneas vacías excesivas
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(lines)
            
            if len(clean_text) > max_chars:
                return clean_text[:max_chars] + f"\n... [Contenido truncado a {max_chars} caracteres]"
            
            return clean_text if clean_text else "La página no contiene texto legible relevante."
            
    except Exception as e:
        return f"Error al leer la URL '{url}': {str(e)}"


# Definiciones de herramientas para Function Calling
TOOLS_METADATA = [
    {
        "name": "web_search",
        "description": "Busca información actualizada en la web en tiempo real. Úsalo para noticias recientes, hechos comprobables, documentación técnica o cualquier consulta que requiera información externa.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "La consulta de búsqueda optimizada para motores de búsqueda (ej. 'noticias DeepSeek R1 2026', 'lanzamiento python 3.13')."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número de resultados a obtener (de 1 a 6)."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_web_page",
        "description": "Lee el contenido detallado de un enlace o artículo web específico obtenido en los resultados de búsqueda.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "La URL del artículo o sitio web que se desea inspeccionar a fondo."
                }
            },
            "required": ["url"]
        }
    }
]
