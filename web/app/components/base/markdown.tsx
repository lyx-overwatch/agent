import ReactMarkdown from 'react-markdown';
import RemarkMath from 'remark-math';
import RemarkBreaks from 'remark-breaks';
import RehypeKatex from 'rehype-katex';
import RemarkGfm from 'remark-gfm';
import React, { useRef, useState, RefObject, useEffect } from 'react';
import { CodeBlock } from './code-block';
import 'katex/dist/katex.min.css';

export function PreCode(props: { children: any }) {
  const ref = useRef<HTMLPreElement>(null);

  return (
    <pre ref={ref}>
      <span
        className='copy-code-button'
        onClick={() => {
          if (ref.current) {
            const code = ref.current.innerText;
            // copyToClipboard(code);
          }
        }}
      ></span>
      {props.children}
    </pre>
  );
}

const useLazyLoad = (ref: RefObject<Element>): boolean => {
  const [isIntersecting, setIntersecting] = useState<boolean>(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setIntersecting(true);
        observer.disconnect();
      }
    });

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => {
      observer.disconnect();
    };
  }, [ref]);

  return isIntersecting;
};

export const Markdown = React.memo(
  ({
    content,
    isStreamEnd,
    isMainChat,
  }: {
    content: string;
    isStreamEnd?: boolean;
    isMainChat?: boolean;
  }) => {
    const ref = useRef<HTMLDivElement>(null);

    // 数学公式处理
    const preprocessContent = (content: string) => {
      let processed = content
        // 处理智谱返回
        .replace(/【\d+†source】/g, '');

      processed = processed.replace(
        /\\\[\s*\\begin\{align\*\}([\s\S]*?)\\end\{align\*\}\s*\\\]/g,
        (match, content) => {
          // 按 \\ 分割行，并过滤空行
          return content
            .split('\\\\')
            .map((line: any) => line.trim())
            .filter((line: any) => line.length > 0)
            .map((line: any) => {
              const cleaned = line.replace(/&/g, '');
              return `$$ ${cleaned} $$`;
            })
            .join('\n');
        }
      );

      processed = processed.replace(
        /\$\s*([^$]*?)\\begin\{array\}([^}]*)\}([\s\S]*?)\\end\{array\}([^$]*?)\s*\$/g,
        (match, prefix, arraySpec, arrayContent, suffix) => {
          // 保持原始的 array 环境结构，但确保在块级公式中
          return `$$${prefix}\\begin{array}${
            arraySpec ? `{${arraySpec}}` : ''
          } ${arrayContent} \\end{array}${suffix}$$`;
        }
      );

      // 处理行内公式 \(...\) → $...$
      processed = processed
        .replace(/\\\(/g, '$')
        .replace(/\\\)/g, '$')
        // 处理块级公式 \[...\] → $$...$$
        .replace(/\\\[/g, '$$')
        .replace(/\\\]/g, '$$')
        // 处理可能存在的转义反斜杠（如API返回的内容）
        .replace(/\\\\\(/g, '$')
        .replace(/\\\\\)/g, '$')
        .replace(/\\\\\[/g, '$$')
        .replace(/\\\\\]/g, '$$');

      return processed;
    };

    useEffect(() => {
      const root = ref.current;
      if (root && isMainChat) {
        const chd = document.createElement('div');
        chd.className = 'focusLine';
        if (content) {
          const lastElem = root.lastElementChild;

          const notPre = lastElem && lastElem.tagName !== 'PRE';

          if (!isStreamEnd && notPre) {
            if (lastElem) {
              window.requestAnimationFrame(() => {
                lastElem.appendChild(chd);
              });
              return () => {
                window.requestAnimationFrame(() => {
                  lastElem.removeChild(chd);
                });
              };
            }
          }
        }
      }
    }, [content, isStreamEnd, isMainChat]);

    return (
      <div className='markdown-body' ref={ref}>
        <ReactMarkdown
          remarkPlugins={[RemarkMath, RemarkGfm, RemarkBreaks]}
          rehypePlugins={[RehypeKatex]}
          components={{
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              return match ? (
                <CodeBlock
                  {...props}
                  children={String(children).replace(/\n$/, '')}
                  language={match[1]}
                />
              ) : (
                <code {...props} className={className}>
                  {children}
                </code>
              );
            },
            img({ src, alt }) {
              if (!src) return null;
              const srcStr = String(src);
              return (
                <a
                  className='py-1 text-[#0072ff] whitespace-nowrap'
                  href={srcStr}
                  target='_blank'
                  rel='noopener noreferrer'
                >
                  {alt || srcStr}
                </a>
              );
            },
            a({ href, children }) {
              return (
                <a href={href} target='_blank' rel='noopener noreferrer'>
                  {children}
                </a>
              );
            },
          }}
        >
          {preprocessContent(content)}
        </ReactMarkdown>
      </div>
    );
  }
);
