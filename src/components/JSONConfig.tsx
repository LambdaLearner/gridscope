import { Copy, Check } from 'lucide-react';
import { useState } from 'react';
import { ExperimentConfig } from '../types/config';

interface JSONConfigProps {
  config: ExperimentConfig | null;
}

export function JSONConfig({ config }: JSONConfigProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!config) return;

    try {
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  if (!config) {
    return (
      <div className="bg-gray-50 rounded-lg p-8 border border-gray-200 text-center">
        <p className="text-gray-500">Generate a plan to see the configuration</p>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-700">Generated Configuration</h3>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-4 h-4 text-green-600" />
              Copied!
            </>
          ) : (
            <>
              <Copy className="w-4 h-4" />
              Copy
            </>
          )}
        </button>
      </div>
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-xs font-mono max-h-96 overflow-y-auto">
        {JSON.stringify(config, null, 2)}
      </pre>
    </div>
  );
}
