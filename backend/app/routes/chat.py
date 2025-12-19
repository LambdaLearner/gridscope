"""Chat API endpoints for the LLM microscopy assistant."""

import os
from fastapi import APIRouter, HTTPException
from ..models.schemas import ChatRequest, ChatResponse, ChatMessage
from ..services.llm_agent import LLMAgent

router = APIRouter(prefix="/chat", tags=["chat"])


def get_agent() -> LLMAgent:
    """Get or create the LLM agent instance."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY environment variable."
        )
    return LLMAgent(api_key)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a chat message and return the assistant's response.
    
    Args:
        request: Chat request containing messages and optional context
        
    Returns:
        ChatResponse with the assistant's message and optional suggestions
    """
    try:
        agent = get_agent()
        
        response_text = await agent.chat(
            messages=request.messages,
            experiment_config=request.experiment_config,
            additional_context=request.context,
        )
        
        # Parse response for suggested actions and code blocks
        suggested_actions = []
        generated_code = None
        
        # Check if response contains code
        if "```python" in response_text:
            # Extract code block
            code_start = response_text.find("```python") + 9
            code_end = response_text.find("```", code_start)
            if code_end > code_start:
                generated_code = response_text[code_start:code_end].strip()
        
        # Look for action suggestions
        action_keywords = [
            "I suggest",
            "You could",
            "Consider",
            "Try",
            "Recommended",
        ]
        
        for line in response_text.split("\n"):
            for keyword in action_keywords:
                if keyword in line and len(line) < 200:
                    suggested_actions.append(line.strip())
                    break
        
        return ChatResponse(
            message=response_text,
            suggested_actions=suggested_actions[:5],  # Limit to 5 suggestions
            generated_code=generated_code,
            explanation=None,
        )
        
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@router.post("/analyze")
async def analyze_objective(objective: str):
    """Analyze a user's experimental objective.
    
    Args:
        objective: Description of what the user wants to accomplish
        
    Returns:
        Analysis with extracted parameters and suggestions
    """
    try:
        agent = get_agent()
        analysis = await agent.analyze_objective(objective)
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/quick-help")
async def quick_help(topic: str):
    """Get quick help on a microscopy topic.
    
    Args:
        topic: The topic to get help about
        
    Returns:
        Quick explanation of the topic
    """
    try:
        agent = get_agent()
        
        messages = [
            ChatMessage(
                role="user",
                content=f"Briefly explain (in 2-3 sentences) this microscopy concept: {topic}"
            )
        ]
        
        response = await agent.chat(messages)
        
        return {"topic": topic, "explanation": response}
        
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Help request failed: {str(e)}")

