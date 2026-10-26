import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Trash2 } from 'lucide-react'
import { imageBlob } from './api'
import { Button } from './ui'
import type { Match } from './types'

export function CollectionImageEditor({
  match,
  busy,
  save,
  remove,
}: {
  match?: Match
  busy: boolean
  save: (file: File) => Promise<boolean>
  remove?: () => void
}) {
  const [preview, setPreview] = useState<string | null>(null)
  const [pending, setPending] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const savedImage = match?.collection_image
  useEffect(() => {
    let active = true
    let url: string | null = null
    setPreview(null)
    if (pending) {
      url = URL.createObjectURL(pending)
      setPreview(url)
    } else if (match && savedImage) {
      void imageBlob(`/matches/${match.id}/collection-image`)
        .then((blob) => {
          if (!active) return
          url = URL.createObjectURL(blob)
          setPreview(url)
        })
        .catch((e) => {
          if (active) setError((e as Error).message)
        })
    }
    return () => {
      active = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [match?.id, savedImage?.id, pending])
  async function upload(file: File) {
    if (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 10_000_000) {
      setError('Выберите JPG или PNG размером до 10 МБ.')
      return
    }
    setPending(file)
    setUploading(true)
    setError('')
    try {
      if (await save(file)) {
        setPending(null)
        if (input.current) input.current.value = ''
      } else setError('Картинка не сохранена. Проверьте сообщение об ошибке и повторите загрузку.')
    } finally {
      setUploading(false)
    }
  }
  return (
    <section className="collection-image-editor" aria-label="Картинка к посту открытия сбора">
      <h3>Картинка к посту открытия</h3>
      <p className="muted caption">
        Опубликуется вместе с текстом и кнопкой игры, когда откроется сбор. JPG или PNG, до 10 МБ.
      </p>
      {preview && (
        <img
          className="collection-image-preview"
          src={preview}
          alt="Предпросмотр картинки к посту открытия сбора"
        />
      )}
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      {uploading && (
        <p className="muted caption" role="status">
          Сохраняем картинку…
        </p>
      )}
      <div className="inline wrap">
        <input
          ref={input}
          type="file"
          className="image-file-input"
          accept="image/jpeg,image/png"
          aria-label="Выбрать картинку к посту"
          disabled={busy || uploading}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
          }}
        />
        <Button
          className="secondary compact"
          disabled={busy || uploading}
          onClick={() => input.current?.click()}
        >
          <ImagePlus size={16} /> {savedImage ? 'Заменить картинку' : 'Добавить картинку'}
        </Button>
        {pending && !uploading && (
          <Button
            className="secondary compact"
            disabled={busy}
            onClick={() => void upload(pending)}
          >
            Повторить загрузку
          </Button>
        )}
        {savedImage && remove && (
          <Button className="ghost compact" disabled={busy || uploading} onClick={remove}>
            <Trash2 size={15} /> Убрать из поста
          </Button>
        )}
      </div>
      {savedImage && !pending && (
        <p className="muted caption">
          Картинка сохранена для этой игры. До открытия сбора её можно заменить или убрать.
        </p>
      )}
    </section>
  )
}
