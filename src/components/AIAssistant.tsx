import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Bot, Send, Code, Loader2, Sparkles, X, Maximize2, Minimize2, Play, RotateCcw } from 'lucide-react';
import { ExperimentConfig } from '../types/config';
import type { ExecutionPlan } from '../types/execution';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  code?: string;
  executionPlan?: ExecutionPlan;
  timestamp: Date;
}

interface AIAssistantProps {
  experimentConfig: ExperimentConfig | null;
  onCodeGenerated?: (code: string) => void;
  onRunCode?: (code: string, executionPlan?: ExecutionPlan) => void;
}

const INITIAL_MESSAGE: Message = {
  id: '1',
  role: 'assistant',
  content: "Hello! I'm your **STEM Digital Twin** assistant. I can help you:\n\n- **Control the microscope** - move stage, adjust settings, switch imaging/diffraction modes\n- **Switch samples** - Au nanoparticles or FCC crystal\n- **Acquire images** - single shots or grid scans\n- **Generate Python scripts** - for automated experiments\n\nWhat would you like to do?",
  timestamp: new Date(),
};

const QUICK_PROMPTS = [
  "Acquire an image at the current position",
  "Move the stage by 10 µm in X direction and acquire",
  "Run autofocus and then take an image",
  "Scan a 3x3 grid with 5 µm spacing",
];

export function AIAssistant({ experimentConfig, onCodeGenerated, onRunCode }: AIAssistantProps) {
  const [messages, setMessages] = useState<Message[]>([INITIAL_MESSAGE]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [showCode, setShowCode] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async (content: string) => {
    if (!content.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: [...messages, userMessage].map(m => ({
            role: m.role,
            content: m.content,
          })),
          experiment_config: experimentConfig,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to get response');
      }

      const data = await response.json();
      
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.message,
        code: data.generated_code,
        executionPlan: data.execution_plan,
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, assistantMessage]);

      if (data.generated_code && onCodeGenerated) {
        onCodeGenerated(data.generated_code);
      }
    } catch (error) {
      console.error('Chat error:', error);
      
      const fallbackMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: "I'm having trouble connecting to the backend server. Please make sure it's running on `http://localhost:8000`.\n\n```bash\ncd backend\npython run.py\n```",
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, fallbackMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const generateCode = async () => {
    setIsLoading(true);

    try {
      const response = await fetch('http://localhost:8000/api/code/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          objective: messages.length > 1 
            ? messages[messages.length - 1].content 
            : "Acquire a single image from the STEM Digital Twin",
          experiment_config: experimentConfig,
          microscope_type: "STEM",
          software_api: "digital_twin",
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to generate code');
      }

      const data = await response.json();
      
      const codeMessage: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: `### Generated Python Script\n\n${data.explanation}\n\n${data.warnings.length > 0 ? '⚠️ **Notes:**\n' + data.warnings.map((w: string) => `- ${w}`).join('\n') : ''}`,
        code: data.code,
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, codeMessage]);

      if (onCodeGenerated) {
        onCodeGenerated(data.code);
      }
    } catch (error) {
      console.error('Code generation error:', error);
      
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: "I couldn't connect to the code generation service. Please ensure the backend server is running.",
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleRunCode = (code: string, executionPlan?: ExecutionPlan) => {
    if (onRunCode) {
      onRunCode(code, executionPlan);
    }
    setShowCode(null);
  };

  const clearChat = () => {
    setMessages([{ ...INITIAL_MESSAGE, id: Date.now().toString(), timestamp: new Date() }]);
    setShowCode(null);
  };

  return (
    <div className={`bg-gradient-to-br from-slate-900 to-slate-800 rounded-xl shadow-2xl border border-slate-700 flex flex-col transition-all duration-300 ${isExpanded ? 'fixed inset-4 z-50' : 'h-[600px]'}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 bg-slate-800/50 rounded-t-xl">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-gradient-to-br from-violet-500 to-fuchsia-500 rounded-lg">
            <Bot className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-white text-sm">AI Assistant</h3>
            <p className="text-[10px] text-slate-400">STEM Digital Twin</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={generateCode}
            disabled={isLoading}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-violet-600 hover:bg-violet-700 text-white rounded-md transition-colors disabled:opacity-50"
          >
            <Code className="w-3 h-3" />
            Generate Script
          </button>
          {messages.length > 1 && (
            <button
              onClick={clearChat}
              disabled={isLoading}
              className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-md transition-colors disabled:opacity-50"
              title="Clear chat"
            >
              <RotateCcw className="w-3 h-3" />
              Clear
            </button>
          )}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 hover:bg-slate-700 rounded-md transition-colors"
          >
            {isExpanded ? (
              <Minimize2 className="w-4 h-4 text-slate-400" />
            ) : (
              <Maximize2 className="w-4 h-4 text-slate-400" />
            )}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-2.5 ${
                message.role === 'user'
                  ? 'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white'
                  : 'bg-slate-700/50 text-slate-100 border border-slate-600'
              }`}
            >
              <div className="text-sm prose prose-invert prose-sm max-w-none">
                <ReactMarkdown
                  components={{
                    code: ({ className, children, ...props }) => {
                      const isInline = !className;
                      if (isInline) {
                        return (
                          <code className="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300 text-xs" {...props}>
                            {children}
                          </code>
                        );
                      }
                      return (
                        <pre className="bg-slate-900 p-3 rounded-lg overflow-x-auto my-2">
                          <code className="text-xs text-slate-300" {...props}>{children}</code>
                        </pre>
                      );
                    },
                    h3: ({ children }) => <h3 className="text-base font-semibold text-white mt-2 mb-1">{children}</h3>,
                    h4: ({ children }) => <h4 className="text-sm font-semibold text-white mt-2 mb-1">{children}</h4>,
                    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                    ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="text-slate-200">{children}</li>,
                    strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
                    a: ({ href, children }) => <a href={href} className="text-cyan-400 hover:underline">{children}</a>,
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
              
              {message.code && (
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => setShowCode(message.code || null)}
                    className="flex items-center gap-1 text-xs text-violet-300 hover:text-violet-200 transition-colors bg-slate-800/50 px-2 py-1 rounded"
                  >
                    <Code className="w-3 h-3" />
                    View Code
                  </button>
                  {onRunCode && (
                    <button
                      onClick={() => handleRunCode(message.code!, message.executionPlan)}
                      className="flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200 transition-colors bg-emerald-900/30 px-2 py-1 rounded"
                    >
                      <Play className="w-3 h-3" />
                      Run on Microscope
                    </button>
                  )}
                </div>
              )}
              
              <span className="text-[10px] opacity-50 mt-1 block">
                {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          </div>
        ))}
        
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-slate-700/50 border border-slate-600 rounded-2xl px-4 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 text-violet-400 animate-spin" />
                <span className="text-sm text-slate-300">Thinking...</span>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompts */}
      {messages.length <= 2 && (
        <div className="px-4 pb-2">
          <p className="text-[10px] text-slate-500 mb-2">Quick actions:</p>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_PROMPTS.map((prompt, index) => (
              <button
                key={index}
                onClick={() => sendMessage(prompt)}
                className="text-[11px] px-2 py-1 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-full border border-slate-600 transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-slate-700">
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Describe what you want to do..."
              className="w-full px-4 py-2.5 bg-slate-700/50 border border-slate-600 rounded-xl text-sm text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
              disabled={isLoading}
            />
            <Sparkles className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          </div>
          <button
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            className="p-2.5 bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-700 hover:to-fuchsia-700 text-white rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Code Modal */}
      {showCode && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 rounded-xl shadow-2xl border border-slate-700 w-full max-w-4xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
              <h3 className="font-semibold text-white">Generated Python Code</h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(showCode);
                  }}
                  className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors"
                >
                  Copy
                </button>
                <button
                  onClick={() => {
                    const blob = new Blob([showCode], { type: 'text/plain' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `microscopy_script_${Date.now()}.py`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors"
                >
                  Download
                </button>
                {onRunCode && (
                  <button
                    onClick={() => handleRunCode(showCode)}
                    className="px-3 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white rounded-md transition-colors flex items-center gap-1"
                  >
                    <Play className="w-3 h-3" />
                    Run
                  </button>
                )}
                <button
                  onClick={() => setShowCode(null)}
                  className="p-1.5 hover:bg-slate-700 rounded-md transition-colors"
                >
                  <X className="w-4 h-4 text-slate-400" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <pre className="text-sm text-slate-300 font-mono whitespace-pre-wrap">
                {showCode}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
