import ArticleView from '@/pages/ArticleView'
import Home from '@/pages/Home'
import { useHashPath } from '@/lib/router'

export default function App() {
  const path = useHashPath()
  const article = path.match(/^\/articles\/([0-9a-f]{32})$/)
  return article ? <ArticleView key={article[1]} id={article[1]} /> : <Home />
}
