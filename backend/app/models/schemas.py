from typing import Optional, Literal
from pydantic import BaseModel, Field


class StagePosition(BaseModel):
    x: float
    y: float


class GridConfig(BaseModel):
    rows: int
    cols: int
    overlap_percent: float
    step_size: float


class TilePosition(BaseModel):
    tile_index: int
    row: int
    col: int
    x: float
    y: float


class ExperimentConfig(BaseModel):
    """Configuration for a microscopy experiment."""
    fov: float = Field(..., description="Field of view size")
    fov_unit: Literal["µm", "nm"] = Field(default="µm", description="FOV unit")
    voltage_kv: float = Field(..., description="Voltage in kilovolts")
    current_value: float = Field(..., description="Current value")
    current_unit: Literal["pA", "nA"] = Field(default="pA", description="Current unit")
    grid: GridConfig
    start_pos: StagePosition
    autofocus_each_tile: bool = True
    auto_aberration_each_tile: bool = False
    dwell_s: float = Field(..., description="Dwell time in seconds")
    tiles: list[TilePosition] = []


class ChatMessage(BaseModel):
    """A single message in the chat conversation."""
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Request for chat completion."""
    messages: list[ChatMessage]
    experiment_config: Optional[ExperimentConfig] = None
    context: Optional[str] = None


class ChatResponse(BaseModel):
    """Response from chat completion."""
    message: str
    suggested_actions: list[str] = []
    generated_code: Optional[str] = None
    explanation: Optional[str] = None


class CodeGenerationRequest(BaseModel):
    """Request for Python code generation."""
    objective: str = Field(..., description="What the user wants to accomplish")
    experiment_config: Optional[ExperimentConfig] = None
    microscope_type: str = Field(default="SEM", description="Type of microscope (SEM, TEM, etc.)")
    software_api: str = Field(default="generic", description="Target software API (e.g., PyJEM, fibsem)")
    additional_requirements: Optional[str] = None


class CodeGenerationResponse(BaseModel):
    """Response containing generated Python code."""
    code: str
    explanation: str
    warnings: list[str] = []
    suggested_modifications: list[str] = []


class MicroscopyAction(BaseModel):
    """Represents a microscopy action that can be performed."""
    action_type: str
    parameters: dict
    description: str

