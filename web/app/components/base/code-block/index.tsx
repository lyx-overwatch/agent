'use client';

import SyntaxHighlighter from 'react-syntax-highlighter';
import { atelierHeathLight } from 'react-syntax-highlighter/dist/esm/styles/hljs';
import React from 'react';
import copy from 'copy-to-clipboard';
import { message } from 'antd';
import { Copy } from 'lucide-react';

interface Props {
  language: string;
  children: React.ReactNode;
}

export const CodeBlock = ({ language, children, ...rest }: Props) => {
  const value = String(children).replace(/\n$/, '');

  return (
    <div className='w-full max-w-full relative'>
      <div className='flex items-center justify-between pb-2'>
        <span className='text-xs text-black dark:text-gray-300 font-mono'>
          {language}
        </span>
        <button
          type='button'
          onClick={() => {
            copy(value);
            message.success('复制成功');
          }}
          className='flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 transition-colors'
        >
          <Copy className='h-3.5 w-3.5' />
          复制
        </button>
      </div>
      <SyntaxHighlighter
        {...rest}
        style={atelierHeathLight}
        language={language}
        showLineNumbers
        PreTag='div'
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
};
