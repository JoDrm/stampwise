"""
FastAPI Gateway pour le service PDF Stamp
Fournit une API REST simple qui communique avec le service gRPC existant
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
import grpc
import tempfile
import os
import logging
from enum import Enum

# Import des fichiers protobuf générés
import pdf_service_pb2
import pdf_service_pb2_grpc

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
GRPC_HOST = os.getenv("GRPC_HOST", "localhost")
GRPC_PORT = os.getenv("GRPC_PORT", "50051")
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB

app = FastAPI(
    title="PDF Stamp Service",
    description="""
    Service de tamponnage automatique de documents PDF.

    ## Fonctionnalités

    - **Détection intelligente** des zones blanches sur chaque page
    - **Évitement automatique** du texte, images et QR codes
    - **Numérotation** des pièces (ex: "Pièce n° DOC-1")
    - **Support multi-sources** : URL, Google Drive, OoDrive, upload direct

    ## Architecture

    Cette API REST communique avec un service gRPC de traitement d'images
    pour des performances optimales sur les fichiers volumineux.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== Modèles Pydantic ==============

class SourceType(str, Enum):
    URL = "url"
    GOOGLE_DRIVE = "google_drive"
    OODRIVE = "oodrive"


class GoogleDriveSource(BaseModel):
    """Source Google Drive"""
    file_id: str = Field(..., description="ID du fichier Google Drive")
    access_token: str = Field(..., description="Token d'accès OAuth2")


class OoDriveSource(BaseModel):
    """Source OoDrive"""
    file_id: str = Field(..., description="ID du fichier OoDrive")
    access_token: str = Field(..., description="Token d'accès")


class StampRequest(BaseModel):
    """Requête de tamponnage via URL"""
    pdf_url: Optional[HttpUrl] = Field(None, description="URL du PDF à traiter")
    google_drive: Optional[GoogleDriveSource] = Field(None, description="Source Google Drive")
    oodrive: Optional[OoDriveSource] = Field(None, description="Source OoDrive")
    stamp_url: HttpUrl = Field(..., description="URL de l'image du tampon (PNG recommandé)")
    document_index: int = Field(1, ge=1, description="Numéro de la pièce")
    prefix: str = Field("", description="Préfixe pour la numérotation (ex: 'DOC')")
    stamp_only_first_page: bool = Field(False, description="Tamponner uniquement la première page")

    class Config:
        json_schema_extra = {
            "example": {
                "pdf_url": "https://example.com/document.pdf",
                "stamp_url": "https://example.com/stamp.png",
                "document_index": 1,
                "prefix": "DOC",
                "stamp_only_first_page": False
            }
        }


class CoordinatesResponse(BaseModel):
    """Coordonnées d'un tampon placé"""
    page_number: int
    x: float
    y: float
    size: float


class StampResponse(BaseModel):
    """Réponse du tamponnage (métadonnées uniquement)"""
    success: bool
    message: str
    coordinates: List[CoordinatesResponse]
    pages_processed: int


class HealthResponse(BaseModel):
    """Réponse du health check"""
    status: str
    grpc_service: str
    version: str


# ============== Client gRPC ==============

class GRPCClient:
    """Client gRPC pour communiquer avec le service de traitement PDF"""

    def __init__(self):
        self.channel = None
        self.stub = None

    def connect(self):
        """Établit la connexion gRPC"""
        if self.channel is None:
            self.channel = grpc.insecure_channel(
                f"{GRPC_HOST}:{GRPC_PORT}",
                options=[
                    ('grpc.max_send_message_length', MAX_FILE_SIZE),
                    ('grpc.max_receive_message_length', MAX_FILE_SIZE),
                ]
            )
            self.stub = pdf_service_pb2_grpc.PDFServiceStub(self.channel)
        return self.stub

    def close(self):
        """Ferme la connexion"""
        if self.channel:
            self.channel.close()
            self.channel = None
            self.stub = None

    def process_pdf(self, request: pdf_service_pb2.PDFRequest) -> pdf_service_pb2.PDFResponse:
        """Appelle le service gRPC pour traiter le PDF"""
        stub = self.connect()
        try:
            response = stub.ProcessPDF(request, timeout=300)  # 5 minutes timeout
            return response
        except grpc.RpcError as e:
            logger.error(f"Erreur gRPC: {e.code()} - {e.details()}")
            raise


# Instance globale du client
grpc_client = GRPCClient()


def get_grpc_client() -> GRPCClient:
    """Dependency injection pour le client gRPC"""
    return grpc_client


# ============== Endpoints ==============

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Vérifie l'état du service et la connectivité gRPC
    """
    grpc_status = "unknown"
    try:
        # Test de connexion gRPC
        channel = grpc.insecure_channel(f"{GRPC_HOST}:{GRPC_PORT}")
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            grpc_status = "connected"
        except grpc.FutureTimeoutError:
            grpc_status = "timeout"
        finally:
            channel.close()
    except Exception as e:
        grpc_status = f"error: {str(e)}"

    return HealthResponse(
        status="healthy",
        grpc_service=grpc_status,
        version="1.0.0"
    )


@app.post(
    "/stamp",
    tags=["PDF Processing"],
    summary="Tamponner un PDF via URL",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF tamponné"
        },
        400: {"description": "Requête invalide"},
        500: {"description": "Erreur de traitement"}
    }
)
async def stamp_pdf_from_url(
    request: StampRequest,
    client: GRPCClient = Depends(get_grpc_client)
):
    """
    Tamponne un PDF à partir d'une URL ou d'un service cloud.

    ## Sources supportées

    - **URL directe** : Fournir `pdf_url`
    - **Google Drive** : Fournir `google_drive.file_id` et `google_drive.access_token`
    - **OoDrive** : Fournir `oodrive.file_id` et `oodrive.access_token`

    ## Retour

    Le PDF tamponné est retourné directement en réponse (application/pdf).
    Les coordonnées des tampons sont disponibles dans les headers:
    - `X-Stamp-Coordinates`: JSON des positions
    - `X-Pages-Processed`: Nombre de pages traitées
    """

    # Validation : au moins une source doit être fournie
    if not request.pdf_url and not request.google_drive and not request.oodrive:
        raise HTTPException(
            status_code=400,
            detail="Au moins une source PDF doit être fournie (pdf_url, google_drive ou oodrive)"
        )

    # Construction de la requête gRPC
    grpc_request = pdf_service_pb2.PDFRequest(
        pdf_url=str(request.pdf_url) if request.pdf_url else "",
        stamp_url=str(request.stamp_url),
        document_index=request.document_index,
        prefix=request.prefix,
        stampOnlyFirstPage=request.stamp_only_first_page
    )

    # Ajout de la source Google Drive si présente
    if request.google_drive:
        grpc_request.googleDriveFile.id = request.google_drive.file_id
        grpc_request.googleDriveFile.accessToken = request.google_drive.access_token

    # Ajout de la source OoDrive si présente
    if request.oodrive:
        grpc_request.ooDriveFile.id = request.oodrive.file_id
        grpc_request.ooDriveFile.accessToken = request.oodrive.access_token

    try:
        # Appel gRPC
        logger.info(f"Traitement PDF - Index: {request.document_index}, Prefix: {request.prefix}")
        response = client.process_pdf(grpc_request)

        # Extraction des coordonnées pour les headers
        coordinates = [
            {
                "page_number": coord.page_number,
                "x": coord.x,
                "y": coord.y,
                "size": coord.size
            }
            for coord in response.coordinates
        ]

        import json

        # Retour du PDF avec métadonnées dans les headers
        return Response(
            content=response.processed_pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="stamped_{request.prefix}_{request.document_index}.pdf"',
                "X-Stamp-Coordinates": json.dumps(coordinates),
                "X-Pages-Processed": str(len(coordinates))
            }
        )

    except grpc.RpcError as e:
        logger.error(f"Erreur gRPC: {e.code()} - {e.details()}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de traitement: {e.details()}"
        )
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur inattendue: {str(e)}"
        )


@app.post(
    "/stamp/upload",
    tags=["PDF Processing"],
    summary="Tamponner un PDF uploadé",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF tamponné"
        },
        400: {"description": "Requête invalide"},
        413: {"description": "Fichier trop volumineux"},
        500: {"description": "Erreur de traitement"}
    }
)
async def stamp_pdf_upload(
    pdf_file: UploadFile = File(..., description="Fichier PDF à tamponner"),
    stamp_url: str = Form(..., description="URL de l'image du tampon"),
    document_index: int = Form(1, ge=1, description="Numéro de la pièce"),
    prefix: str = Form("", description="Préfixe pour la numérotation"),
    stamp_only_first_page: bool = Form(False, description="Tamponner uniquement la première page"),
    client: GRPCClient = Depends(get_grpc_client)
):
    """
    Tamponne un PDF uploadé directement.

    ## Utilisation

    Envoyez le fichier PDF en multipart/form-data avec les paramètres.

    ## Limites

    - Taille max: 200MB
    - Formats acceptés: PDF uniquement

    ## Exemple curl

    ```bash
    curl -X POST "http://localhost:8000/stamp/upload" \\
      -F "pdf_file=@document.pdf" \\
      -F "stamp_url=https://example.com/stamp.png" \\
      -F "document_index=1" \\
      -F "prefix=DOC" \\
      --output stamped.pdf
    ```
    """

    # Validation du type de fichier
    if not pdf_file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un PDF"
        )

    # Lecture du fichier
    content = await pdf_file.read()

    # Vérification de la taille
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux. Maximum: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Sauvegarde temporaire du PDF pour le traitement
    # Note: Dans une version future, on pourrait modifier le service gRPC
    # pour accepter les bytes directement
    temp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(content)
            temp_pdf = f.name

        # Pour l'instant, on utilise une URL locale temporaire
        # TODO: Améliorer en passant les bytes directement au service gRPC
        # ou en utilisant un stockage temporaire accessible par URL

        raise HTTPException(
            status_code=501,
            detail="Upload direct non encore implémenté. Utilisez /stamp avec une URL pour le moment."
        )

    finally:
        if temp_pdf and os.path.exists(temp_pdf):
            os.remove(temp_pdf)


@app.post(
    "/stamp/metadata",
    response_model=StampResponse,
    tags=["PDF Processing"],
    summary="Tamponner et obtenir les métadonnées"
)
async def stamp_pdf_metadata(
    request: StampRequest,
    client: GRPCClient = Depends(get_grpc_client)
):
    """
    Tamponne un PDF et retourne les métadonnées (sans le PDF).

    Utile pour :
    - Vérifier les positions des tampons avant téléchargement
    - Intégrations où seules les métadonnées sont nécessaires
    """

    if not request.pdf_url and not request.google_drive and not request.oodrive:
        raise HTTPException(
            status_code=400,
            detail="Au moins une source PDF doit être fournie"
        )

    grpc_request = pdf_service_pb2.PDFRequest(
        pdf_url=str(request.pdf_url) if request.pdf_url else "",
        stamp_url=str(request.stamp_url),
        document_index=request.document_index,
        prefix=request.prefix,
        stampOnlyFirstPage=request.stamp_only_first_page
    )

    if request.google_drive:
        grpc_request.googleDriveFile.id = request.google_drive.file_id
        grpc_request.googleDriveFile.accessToken = request.google_drive.access_token

    if request.oodrive:
        grpc_request.ooDriveFile.id = request.oodrive.file_id
        grpc_request.ooDriveFile.accessToken = request.oodrive.access_token

    try:
        response = client.process_pdf(grpc_request)

        coordinates = [
            CoordinatesResponse(
                page_number=coord.page_number,
                x=coord.x,
                y=coord.y,
                size=coord.size
            )
            for coord in response.coordinates
        ]

        return StampResponse(
            success=True,
            message="PDF tamponné avec succès",
            coordinates=coordinates,
            pages_processed=len(coordinates)
        )

    except grpc.RpcError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur de traitement: {e.details()}"
        )


# ============== Événements de lifecycle ==============

@app.on_event("startup")
async def startup_event():
    """Initialisation au démarrage"""
    logger.info("Démarrage du gateway FastAPI")
    logger.info(f"Connexion gRPC configurée vers {GRPC_HOST}:{GRPC_PORT}")


@app.on_event("shutdown")
async def shutdown_event():
    """Nettoyage à l'arrêt"""
    logger.info("Arrêt du gateway FastAPI")
    grpc_client.close()


# ============== Point d'entrée ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_gateway:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
