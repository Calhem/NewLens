// A tiny hash router: "#/" is the home page, "#/articles/<id>" an article.
// Hash routes need no server configuration and keep the browser's back button working.

import { useEffect, useState } from 'react'

export function useHashPath() {
  const read = () => window.location.hash.replace(/^#/, '') || '/'
  const [path, setPath] = useState(read)
  useEffect(() => {
    const onChange = () => setPath(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return path
}

export const articlePath = (id: string) => `#/articles/${id}`
