import { useState, useCallback } from 'react';
import { Microscope } from 'lucide-react';
import { AIAssistant } from './components/AIAssistant';
import { MicroscopeViewer } from './components/MicroscopeViewer';
import { ExecutionPanel } from './components/ExecutionPanel';
import { MicroscopeLogsPanel } from './components/MicroscopeLogsPanel';
import { getMicroscopeStatus, type MicroscopeState, type AcquireResult } from './api/digitalTwin';

interface ExecutionLog {
  id: string;
  type: 'info' | 'success' | 'error' | 'image' | 'stage' | 'command';
  message: string;
  timestamp: Date;
  data?: {
    image_base64?: string;
    stage?: { x_um: number; y_um: number; z_um: number; a?: number; b?: number };
    command?: string;
    sampleType?: string;
    mode?: string;
  };
}

interface AcquiredImage {
  image_base64: string;
  x_um: number;
  y_um: number;
  z_um?: number;
  a?: number;  // alpha tilt
  b?: number;  // beta tilt
  sampleType?: string;
  mode?: string;
}

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [microscopeState, setMicroscopeState] = useState<MicroscopeState | null>(null);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [acquiredImages, setAcquiredImages] = useState<AcquiredImage[]>([]);
  const [currentSampleType, setCurrentSampleType] = useState<string>('au_nanoparticles');
  const [currentMode, setCurrentMode] = useState<string>('IMG');

  // Handle microscope state updates from viewer
  const handleMicroscopeStateChange = useCallback((state: MicroscopeState) => {
    setMicroscopeState(state);
    setIsConnected(true);
    if (state.sample_type) {
      setCurrentSampleType(state.sample_type);
    }
    if (state.mode) {
      setCurrentMode(state.mode);
    }
  }, []);

  // Handle image acquisition from viewer
  const handleImageAcquired = useCallback((result: AcquireResult) => {
    if (result.image?.image_base64) {
      setAcquiredImages(prev => [...prev, {
        image_base64: result.image.image_base64!,
        x_um: result.stage.x_um,
        y_um: result.stage.y_um,
        z_um: result.stage.z_um,
        sampleType: currentSampleType,
        mode: currentMode,
      }]);
      
      addExecutionLog('image', `Image acquired at (${result.stage.x_um.toFixed(2)}, ${result.stage.y_um.toFixed(2)}) µm`, {
        image_base64: result.image.image_base64,
        stage: result.stage,
        sampleType: currentSampleType,
        mode: currentMode,
      });
    }
  }, [currentSampleType, currentMode]);

  // Add execution log
  const addExecutionLog = (type: ExecutionLog['type'], message: string, data?: ExecutionLog['data']) => {
    setExecutionLogs(prev => [...prev, {
      id: Date.now().toString(),
      type,
      message,
      timestamp: new Date(),
      data,
    }]);
  };

  // Handle code generation
  const handleCodeGenerated = useCallback((code: string) => {
    setGeneratedCode(code);
    addExecutionLog('info', 'Code generated and ready to execute');
  }, []);

  // Helper function to acquire and add image
  const acquireAndAddImage = async (label?: string) => {
    // First get current state to know sample type, mode, and tilt
    let stateInfo = { sampleType: currentSampleType, mode: currentMode, a: 0, b: 0 };
    try {
      const statusResp = await fetch('http://localhost:8000/api/microscope/status');
      if (statusResp.ok) {
        const status = await statusResp.json();
        if (status.state) {
          stateInfo = {
            sampleType: status.state.sample_type || currentSampleType,
            mode: status.state.mode || currentMode,
            a: status.state.stage?.a || 0,
            b: status.state.stage?.b || 0,
          };
          setCurrentSampleType(stateInfo.sampleType);
          setCurrentMode(stateInfo.mode);
        }
      }
    } catch {
      // ignore
    }
    
    const response = await fetch('http://localhost:8000/api/execute/simple', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'acquire', params: {} }),
    });
    
    if (response.ok) {
      const result = await response.json();
      if (result.image?.image_base64) {
        setAcquiredImages(prev => [...prev, {
          image_base64: result.image.image_base64,
          x_um: result.stage.x_um,
          y_um: result.stage.y_um,
          z_um: result.stage.z_um,
          a: stateInfo.a,
          b: stateInfo.b,
          sampleType: stateInfo.sampleType,
          mode: stateInfo.mode,
        }]);
        addExecutionLog('image', label || `📷 Image acquired at (${result.stage.x_um.toFixed(2)}, ${result.stage.y_um.toFixed(2)}) µm`, {
          image_base64: result.image.image_base64,
          stage: { ...result.stage, a: stateInfo.a, b: stateInfo.b },
          sampleType: stateInfo.sampleType,
          mode: stateInfo.mode,
        });
        return result;
      }
    }
    return null;
  };

  // Helper to detect tilt scan from code
  const detectTiltScan = (code: string): { alphaValues: number[]; betaValues: number[] } | null => {
    // Check for patterns like "explore different a and b values" or "tilt series"
    const isTiltExploration = /(?:explore|vary|different|scan|series).*(?:tilt|alpha|beta|a\s+and\s+b)/i.test(code);
    
    let alphaValues: number[] = [];
    let betaValues: number[] = [];
    
    // Look for Python list assignments like: alpha_angles = [0, 10, 20, 30, 40, 50, 60]
    const alphaListMatch = code.match(/alpha_?(?:angles?|values?)?\s*=\s*\[([^\]]+)\]/i);
    const betaListMatch = code.match(/beta_?(?:angles?|values?)?\s*=\s*\[([^\]]+)\]/i);
    
    // Also check for just 'a' and 'b' variable names with lists
    const aListMatch = code.match(/\ba\s*=\s*\[([^\]]+)\]/);
    const bListMatch = code.match(/\bb\s*=\s*\[([^\]]+)\]/);
    
    // Parse alpha values
    const alphaSource = alphaListMatch?.[1] || aListMatch?.[1];
    if (alphaSource) {
      alphaValues = alphaSource.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    }
    
    // Parse beta values
    const betaSource = betaListMatch?.[1] || bListMatch?.[1];
    if (betaSource) {
      betaValues = betaSource.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    }
    
    // If no list found, look for range patterns in comments/docstrings
    // Pattern: "0 to 60 with step 10" or "from 0 to 60 step 10"
    if (alphaValues.length === 0 || betaValues.length === 0) {
      const rangeMatch = code.match(/(?:a,?\s*b|alpha.*beta|tilt).*?(\d+)\s*(?:to|through|-)\s*(\d+).*?(?:step|increment)\s*(?:of\s*)?(\d+)/i);
      if (rangeMatch) {
        const start = parseInt(rangeMatch[1]);
        const end = parseInt(rangeMatch[2]);
        const step = parseInt(rangeMatch[3]);
        const values: number[] = [];
        for (let v = start; v <= end; v += step) {
          values.push(v);
        }
        if (alphaValues.length === 0) alphaValues = values;
        if (betaValues.length === 0) betaValues = values;
      }
    }
    
    // Look for range() or np.arange() patterns
    // range(0, 70, 10) or np.arange(0, 61, 10)
    if (alphaValues.length === 0) {
      const alphaRangeMatch = code.match(/alpha_?(?:angles?|values?)?\s*=\s*(?:list\()?(?:range|np\.arange)\((\d+),\s*(\d+),?\s*(\d+)?\)/i);
      if (alphaRangeMatch) {
        const start = parseInt(alphaRangeMatch[1]);
        const end = parseInt(alphaRangeMatch[2]);
        const step = alphaRangeMatch[3] ? parseInt(alphaRangeMatch[3]) : 1;
        for (let v = start; v < end; v += step) {
          alphaValues.push(v);
        }
      }
    }
    
    if (betaValues.length === 0) {
      const betaRangeMatch = code.match(/beta_?(?:angles?|values?)?\s*=\s*(?:list\()?(?:range|np\.arange)\((\d+),\s*(\d+),?\s*(\d+)?\)/i);
      if (betaRangeMatch) {
        const start = parseInt(betaRangeMatch[1]);
        const end = parseInt(betaRangeMatch[2]);
        const step = betaRangeMatch[3] ? parseInt(betaRangeMatch[3]) : 1;
        for (let v = start; v < end; v += step) {
          betaValues.push(v);
        }
      }
    }
    
    // Default tilt values if user wants to explore but didn't specify values
    if (isTiltExploration && alphaValues.length === 0 && betaValues.length === 0) {
      // Check if there's a step mentioned in the code
      const stepMatch = code.match(/step\s*(?:of|=|:)?\s*(\d+)/i);
      const step = stepMatch ? parseInt(stepMatch[1]) : 15;
      
      // Check for range in the objective/comments
      const objRangeMatch = code.match(/(\d+)\s*(?:to|through|-)\s*(\d+)/);
      if (objRangeMatch) {
        const start = parseInt(objRangeMatch[1]);
        const end = parseInt(objRangeMatch[2]);
        for (let v = start; v <= end; v += step) {
          alphaValues.push(v);
          betaValues.push(v);
        }
      } else {
        // Default range
        alphaValues = [-30, -15, 0, 15, 30];
        betaValues = [-30, -15, 0, 15, 30];
      }
    }
    
    if (alphaValues.length > 0 || betaValues.length > 0) {
      // Ensure at least one value in each array
      if (alphaValues.length === 0) alphaValues = [0];
      if (betaValues.length === 0) betaValues = [0];
      return { alphaValues, betaValues };
    }
    
    return null;
  };

  // Helper to detect and parse grid scan from code
  const detectGridScan = (code: string): { rows: number; cols: number; step_um: number; fov_um: number; autofocus: boolean } | null => {
    // Look for grid configuration in the code
    const rowsMatch = code.match(/["']?grid_rows["']?\s*[:=]\s*(\d+)/i);
    const colsMatch = code.match(/["']?grid_cols["']?\s*[:=]\s*(\d+)/i);
    const stepMatch = code.match(/["']?step_size(?:_um)?["']?\s*[:=]\s*([\d.]+)/i);
    const fovMatch = code.match(/["']?field_of_view(?:_um)?["']?\s*[:=]\s*([\d.]+)/i);
    const autofocusMatch = code.match(/["']?autofocus(?:_enabled)?["']?\s*[:=]\s*(True|False|true|false)/i);
    
    // Also check for NxN grid patterns in comments or objective
    const gridPatternMatch = code.match(/(\d+)\s*[xX×]\s*(\d+)\s*grid/i);
    const spacingMatch = code.match(/(\d+(?:\.\d+)?)\s*(?:µm|um|micrometer)/i);
    
    let rows = rowsMatch ? parseInt(rowsMatch[1]) : (gridPatternMatch ? parseInt(gridPatternMatch[1]) : 0);
    let cols = colsMatch ? parseInt(colsMatch[1]) : (gridPatternMatch ? parseInt(gridPatternMatch[2]) : 0);
    let step = stepMatch ? parseFloat(stepMatch[1]) : (spacingMatch ? parseFloat(spacingMatch[1]) : 10);
    const fov = fovMatch ? parseFloat(fovMatch[1]) : 20;
    const autofocus = autofocusMatch ? autofocusMatch[1].toLowerCase() === 'true' : true;
    
    // If we found both rows and cols, it's a grid scan
    if (rows > 0 && cols > 0) {
      return { rows, cols, step_um: step, fov_um: fov, autofocus };
    }
    
    return null;
  };

  // Run code on digital twin
  const handleRunCode = useCallback(async (code: string) => {
    setIsExecuting(true);
    setExecutionLogs([]); // Clear previous logs
    setAcquiredImages([]); // Clear previous images
    addExecutionLog('info', '🔬 Starting execution on STEM Digital Twin...');
    
    try {
      // Check connection
      const status = await getMicroscopeStatus();
      if (!status.connected) {
        addExecutionLog('error', '❌ Digital Twin not connected. Please start the server.');
        setIsExecuting(false);
        return;
      }
      
      addExecutionLog('success', '✓ Connected to Digital Twin');
      
      // Check if this is a tilt scan
      const tiltParams = detectTiltScan(code);
      
      if (tiltParams) {
        // Execute tilt scan
        const { alphaValues, betaValues } = tiltParams;
        const totalImages = alphaValues.length * betaValues.length;
        
        addExecutionLog('info', `🔄 Detected tilt exploration: α=${alphaValues.join('°, ')}° × β=${betaValues.join('°, ')}°`);
        addExecutionLog('command', `Acquiring ${totalImages} images at different tilt angles...`);
        
        let imageCount = 0;
        for (const alpha of alphaValues) {
          for (const beta of betaValues) {
            imageCount++;
            
            addExecutionLog('command', `[${imageCount}/${totalImages}] Setting tilt α=${alpha}°, β=${beta}°`);
            
            // Set tilt angles
            const tiltResp = await fetch('http://localhost:8000/api/execute/simple', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ 
                action: 'tilt', 
                params: { a: alpha, b: beta, relative: false } 
              }),
            });
            
            if (!tiltResp.ok) {
              addExecutionLog('error', `❌ Failed to set tilt α=${alpha}°, β=${beta}°`);
              continue;
            }
            
            const tiltResult = await tiltResp.json();
            addExecutionLog('success', `✓ Tilt set to α=${tiltResult.new_position?.a?.toFixed(1)}°, β=${tiltResult.new_position?.b?.toFixed(1)}°`);
            
            // Wait a moment for the stage to settle
            await new Promise(r => setTimeout(r, 100));
            
            // Acquire image
            addExecutionLog('command', `[${imageCount}/${totalImages}] Acquiring image...`);
            await acquireAndAddImage(`📷 Image at α=${alpha}°, β=${beta}°`);
            
            // Small delay between acquisitions
            await new Promise(r => setTimeout(r, 150));
          }
        }
        
        addExecutionLog('success', `✅ Tilt exploration complete! Acquired ${totalImages} images.`);
        return;
      }
      
      // Check if this is a grid scan
      const gridParams = detectGridScan(code);
      
      if (gridParams) {
        // Execute as grid scan using backend's proper scan_grid action
        addExecutionLog('info', `📊 Detected ${gridParams.rows}×${gridParams.cols} grid scan (step: ${gridParams.step_um} µm)`);
        addExecutionLog('command', `Starting grid acquisition...`);
        
        const totalTiles = gridParams.rows * gridParams.cols;
        
        // Execute grid scan tile by tile for better feedback
        for (let row = 0; row < gridParams.rows; row++) {
          for (let col = 0; col < gridParams.cols; col++) {
            const tileIdx = row * gridParams.cols + col;
            const x_um = col * gridParams.step_um;
            const y_um = row * gridParams.step_um;
            
            addExecutionLog('command', `[${tileIdx + 1}/${totalTiles}] Moving to (${x_um.toFixed(1)}, ${y_um.toFixed(1)}) µm`);
            
            // Move stage (absolute position)
            const moveResp = await fetch('http://localhost:8000/api/execute/simple', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ 
                action: 'move', 
                params: { x_um, y_um, relative: false } 
              }),
            });
            
            if (!moveResp.ok) {
              addExecutionLog('error', `❌ Failed to move to tile ${tileIdx + 1}`);
              continue;
            }
            
            const moveResult = await moveResp.json();
            addExecutionLog('success', `✓ Stage at (${moveResult.new_position?.x_um?.toFixed(2)}, ${moveResult.new_position?.y_um?.toFixed(2)}, ${moveResult.new_position?.z_um?.toFixed(2) || 0}) µm`);
            
            // Autofocus if enabled
            if (gridParams.autofocus) {
              addExecutionLog('command', `[${tileIdx + 1}/${totalTiles}] Autofocusing...`);
              const afResp = await fetch('http://localhost:8000/api/execute/simple', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'autofocus', params: { z_range_um: 4.0, z_steps: 9 } }),
              });
              
              if (afResp.ok) {
                const afResult = await afResp.json();
                addExecutionLog('success', `✓ Focus adjusted by ${afResult.result?.best_z_um_relative?.toFixed(2) || 0} µm`);
              }
            }
            
            // Acquire image
            addExecutionLog('command', `[${tileIdx + 1}/${totalTiles}] Acquiring image...`);
            await acquireAndAddImage(`📷 Tile ${tileIdx + 1}/${totalTiles} at (${x_um.toFixed(1)}, ${y_um.toFixed(1)}) µm`);
            
            // Small delay between tiles
            await new Promise(r => setTimeout(r, 100));
          }
        }
        
        addExecutionLog('success', `✅ Grid scan complete! Acquired ${totalTiles} images.`);
        
      } else {
        // Fall back to line-by-line execution for non-grid commands
        addExecutionLog('info', '📷 Acquiring initial reference image...');
        await acquireAndAddImage('📷 Initial reference image');
        await new Promise(r => setTimeout(r, 300));
        
        // Parse and execute commands from code
        const lines = code.split('\n');
        let commandCount = 0;
        
        for (const line of lines) {
          // Skip empty lines and comments
          if (!line.trim() || line.trim().startsWith('#')) continue;
          
          if (line.includes('acquire_image') && !line.includes('def ') && !line.includes('# ')) {
            commandCount++;
            addExecutionLog('command', `[${commandCount}] Acquiring image...`);
            await acquireAndAddImage();
            await new Promise(r => setTimeout(r, 300));
          }
          
          if (line.includes('set_stage') && !line.includes('def ')) {
            commandCount++;
            // Try to parse movement values - handle different quote styles and formats
            const xMatch = line.match(/["']?x["']?\s*:\s*(-?[\d.]+(?:e[+-]?\d+)?)/i);
            const yMatch = line.match(/["']?y["']?\s*:\s*(-?[\d.]+(?:e[+-]?\d+)?)/i);
            
            const movements: string[] = [];
            let dx_m = 0, dy_m = 0;
            let hasValidMove = false;
            
            if (xMatch) {
              dx_m = parseFloat(xMatch[1]);
              if (!isNaN(dx_m)) {
                movements.push(`x=${(dx_m * 1e6).toFixed(2)} µm`);
                hasValidMove = true;
              }
            }
            if (yMatch) {
              dy_m = parseFloat(yMatch[1]);
              if (!isNaN(dy_m)) {
                movements.push(`y=${(dy_m * 1e6).toFixed(2)} µm`);
                hasValidMove = true;
              }
            }
            
            if (hasValidMove) {
              addExecutionLog('command', `[${commandCount}] Moving stage: ${movements.join(', ')}`);
              
              // Actually execute the stage move
              try {
                const response = await fetch('http://localhost:8000/api/execute/simple', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ 
                    action: 'move', 
                    params: { dx: dx_m, dy: dy_m } 
                  }),
                });
                
                if (response.ok) {
                  const result = await response.json();
                  addExecutionLog('success', `✓ Stage at (${result.new_position?.x_um?.toFixed(2) || 0}, ${result.new_position?.y_um?.toFixed(2) || 0}, ${result.new_position?.z_um?.toFixed(2) || 0}) µm`);
                  
                  // Acquire image after move to show result
                  await new Promise(r => setTimeout(r, 100));
                  await acquireAndAddImage(`📷 Image after move`);
                }
              } catch (e) {
                addExecutionLog('error', `❌ Stage move failed: ${e}`);
              }
            }
            
            await new Promise(r => setTimeout(r, 200));
          }
          
          if (line.includes('autofocus') && !line.includes('def ') && !line.includes('autofocus_')) {
            commandCount++;
            addExecutionLog('command', `[${commandCount}] Running autofocus...`);
            
            const response = await fetch('http://localhost:8000/api/execute/simple', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: 'autofocus', params: { z_range_um: 4.0, z_steps: 9 } }),
            });
            
            if (response.ok) {
              const result = await response.json();
              addExecutionLog('success', `✓ Autofocus complete: Z adjusted by ${result.result?.best_z_um_relative?.toFixed(2) || 0} µm`);
              
              // Acquire image after autofocus to show result
              await new Promise(r => setTimeout(r, 100));
              await acquireAndAddImage(`📷 Image after autofocus (in focus)`);
            }
            await new Promise(r => setTimeout(r, 300));
          }
          
          if (line.includes('device_settings') && !line.includes('def ')) {
            commandCount++;
            
            // Try to parse FOV
            const fovMatch = line.match(/field_of_view_um\s*[=:]\s*([\d.]+)/);
            if (fovMatch) {
              const fov = parseFloat(fovMatch[1]);
              addExecutionLog('command', `[${commandCount}] Setting FOV to ${fov} µm`);
              
              try {
                await fetch('http://localhost:8000/api/microscope/detectors/haadf', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ field_of_view_um: fov }),
                });
                addExecutionLog('success', `✓ FOV updated to ${fov} µm`);
              } catch (e) {
                addExecutionLog('error', `❌ Failed to set FOV: ${e}`);
              }
            } else {
              addExecutionLog('command', `[${commandCount}] Updating device settings`);
            }
            await new Promise(r => setTimeout(r, 100));
          }
        }
        
        addExecutionLog('success', `✅ Execution complete! ${commandCount} commands executed.`);
      }
      
    } catch (error) {
      addExecutionLog('error', `Execution failed: ${error}`);
    } finally {
      setIsExecuting(false);
    }
  }, []);

  // Start execution
  const handleStartExecution = useCallback(() => {
    if (generatedCode) {
      handleRunCode(generatedCode);
    }
  }, [generatedCode, handleRunCode]);

  // Stop execution
  const handleStopExecution = useCallback(() => {
    setIsExecuting(false);
    addExecutionLog('info', 'Execution stopped by user');
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 sticky top-0 z-40">
        <div className="max-w-[2000px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-xl shadow-lg shadow-violet-500/20">
                <Microscope className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-violet-400 to-cyan-400 bg-clip-text text-transparent">
                  GridScope
                </h1>
                <p className="text-sm text-slate-500">STEM Digital Twin AI Assistant</p>
              </div>
            </div>
            
            {/* Status indicators */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
                <span className="text-sm text-slate-400">
                  {isConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              
              {microscopeState && (
                <div className="hidden md:flex items-center gap-4 text-xs text-slate-500 font-mono">
                  <span>X: {(microscopeState.stage.x * 1e6).toFixed(1)} µm</span>
                  <span>Y: {(microscopeState.stage.y * 1e6).toFixed(1)} µm</span>
                  <span>FOV: {microscopeState.detectors?.haadf?.field_of_view_um || 20} µm</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[2000px] mx-auto px-6 py-6">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          
          {/* Left Column: Microscope Viewer */}
          <div className="xl:col-span-1 space-y-6">
            <MicroscopeViewer 
              onStateChange={handleMicroscopeStateChange}
              onImageAcquired={handleImageAcquired}
            />
            
            {/* Microscope Command Log */}
            <MicroscopeLogsPanel 
              autoRefresh={true}
              refreshInterval={2000}
            />
          </div>
          
          {/* Middle Column: AI Assistant */}
          <div className="xl:col-span-1">
            <AIAssistant
              experimentConfig={null}
              onCodeGenerated={handleCodeGenerated}
              onRunCode={handleRunCode}
            />
          </div>
          
          {/* Right Column: Execution Output */}
          <div className="xl:col-span-1">
            <ExecutionPanel
              code={generatedCode}
              isRunning={isExecuting}
              onStart={handleStartExecution}
              onStop={handleStopExecution}
              logs={executionLogs}
              acquiredImages={acquiredImages}
              currentSampleType={currentSampleType}
              currentMode={currentMode}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
