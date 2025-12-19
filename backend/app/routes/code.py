"""Code generation API endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from ..models.schemas import CodeGenerationRequest, CodeGenerationResponse
from ..services.code_generator import MicroscopyCodeGenerator

router = APIRouter(prefix="/code", tags=["code"])


@router.post("/generate", response_model=CodeGenerationResponse)
async def generate_code(request: CodeGenerationRequest) -> CodeGenerationResponse:
    """Generate Python automation code for microscopy experiments.
    
    Args:
        request: Code generation request with objective and configuration
        
    Returns:
        Generated code with explanation and suggestions
    """
    try:
        generator = MicroscopyCodeGenerator()
        result = await generator.generate(request)
        
        return CodeGenerationResponse(
            code=result["code"],
            explanation=result["explanation"],
            warnings=result.get("warnings", []),
            suggested_modifications=result.get("suggested_modifications", []),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Code generation failed: {str(e)}"
        )


@router.post("/generate/raw", response_class=PlainTextResponse)
async def generate_code_raw(request: CodeGenerationRequest) -> str:
    """Generate Python code and return as plain text (for download).
    
    Args:
        request: Code generation request
        
    Returns:
        Generated Python code as plain text
    """
    try:
        generator = MicroscopyCodeGenerator()
        result = await generator.generate(request)
        return result["code"]
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Code generation failed: {str(e)}"
        )


@router.get("/templates")
async def list_templates():
    """List available code templates."""
    return {
        "templates": [
            {
                "id": "generic",
                "name": "Generic Python",
                "description": "Basic Python script for educational purposes",
            },
            {
                "id": "pyjem",
                "name": "PyJEM",
                "description": "For JEOL microscopes using PyJEM API",
            },
            {
                "id": "fibsem",
                "name": "fibsem",
                "description": "For FIB-SEM systems using fibsem library",
            },
            {
                "id": "autoscript",
                "name": "Autoscript",
                "description": "For Thermo Fisher microscopes",
            },
        ]
    }


@router.get("/apis")
async def list_supported_apis():
    """List supported microscopy software APIs."""
    return {
        "apis": [
            {
                "id": "digital_twin",
                "name": "Digital Twin (Local)",
                "microscopes": ["GridScope TEM Simulator"],
                "install": "Built-in - start with backend server",
                "recommended": True,
            },
            {
                "id": "generic",
                "name": "Generic Python",
                "microscopes": ["Any"],
                "install": "No special installation required",
            },
            {
                "id": "pyjem",
                "name": "PyJEM",
                "microscopes": ["JEOL TEM", "JEOL SEM"],
                "install": "pip install pyjem",
            },
            {
                "id": "fibsem",
                "name": "fibsem",
                "microscopes": ["Thermo Fisher FIB-SEM", "TESCAN FIB-SEM"],
                "install": "pip install fibsem",
            },
            {
                "id": "autoscript",
                "name": "Autoscript",
                "microscopes": ["Thermo Fisher SEM/TEM"],
                "install": "Contact Thermo Fisher for installation",
            },
            {
                "id": "serialem",
                "name": "SerialEM",
                "microscopes": ["Various (Tomography)"],
                "install": "https://bio3d.colorado.edu/SerialEM/",
            },
        ]
    }

