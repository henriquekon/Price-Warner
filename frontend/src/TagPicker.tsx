import { useEffect, useRef, useState } from 'react';
import { Plus, Tag } from 'lucide-react';

type Suggestions = { tags: string[]; recommended: string[] };
const keyOf = (name: string) => name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').trim();

export default function TagPicker({ name, selected, onChange, autoSelect = false }:
  { name: string; selected: string[]; onChange: (tags: string[]) => void; autoSelect?: boolean }) {
  const [catalog, setCatalog] = useState<string[]>([]);
  const [recommended, setRecommended] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const changeRef = useRef(onChange);
  const selectedRef = useRef(selected);
  changeRef.current = onChange;
  selectedRef.current = selected;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    fetch(`/tags/suggest?${new URLSearchParams({ name })}`, {
      credentials: 'same-origin', signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('Unable to load suggested tags');
      return response.json() as Promise<Suggestions>;
    }).then(data => {
      setCatalog(data.tags);
      setRecommended(data.recommended);
      if (autoSelect) {
        const merged = [...selectedRef.current];
        for (const tag of data.recommended) {
          if (merged.length >= 12) break;
          if (!merged.some(value => keyOf(value) === keyOf(tag))) merged.push(tag);
        }
        changeRef.current(merged);
      }
    }).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Unable to load tags');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [name, autoSelect]);

  const options = [...catalog];
  for (const tag of selected) {
    if (!options.some(value => keyOf(value) === keyOf(tag))) options.push(tag);
  }
  options.sort((a, b) => a.localeCompare(b, 'pt-BR'));

  const toggle = (tag: string, checked: boolean) => {
    if (checked) {
      if (selected.length < 12) onChange([...selected, tag]);
    } else {
      onChange(selected.filter(value => keyOf(value) !== keyOf(tag)));
    }
  };
  const addCustom = () => {
    const value = input.trim().replace(/\s+/g, ' ');
    if (value.length < 2 || value.length > 40 || !/[\p{L}\p{N}]/u.test(value)) {
      setError('Use a tag with 2 to 40 characters.');
      return;
    }
    if (selected.length >= 12) {
      setError('Maximum of 12 tags per product.');
      return;
    }
    const matching = options.find(tag => keyOf(tag) === keyOf(value));
    if (!selected.some(tag => keyOf(tag) === keyOf(value))) onChange([...selected, matching ?? value]);
    setCatalog(current => current.some(tag => keyOf(tag) === keyOf(value)) ? current : [...current, value]);
    setInput('');
    setError('');
  };

  return <div className="tag-picker">
    <div className="tag-picker-heading"><Tag size={16}/><strong>Categories and tags</strong><span>{selected.length}/12 selected</span></div>
    <p className="tag-picker-help">Select multiple tags. Learned suggestions are checked automatically when adding a product, and you can uncheck any of them.</p>
    {loading && <p className="tag-picker-help">Finding tags...</p>}
    <div className="tag-choices">
      {options.map(tag => {
        const checked = selected.some(value => keyOf(value) === keyOf(tag));
        const isRecommended = recommended.some(value => keyOf(value) === keyOf(tag));
        return <label className={`tag-choice ${checked ? 'tag-choice-selected' : ''}`} key={keyOf(tag)}>
          <input type="checkbox" checked={checked} disabled={!checked && selected.length >= 12} onChange={event => toggle(tag, event.target.checked)}/>
          <span>{tag}</span>{isRecommended && <small>Suggested</small>}
        </label>;
      })}
      {!loading && !options.length && <p className="tag-picker-help">No tags yet. Create your first one below.</p>}
    </div>
    <div className="tag-create"><input aria-label="New tag name" placeholder="New tag, e.g. RAM" maxLength={40} value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') {event.preventDefault();addCustom();} }}/><button type="button" className="secondary" onClick={addCustom} disabled={!input.trim() || selected.length >= 12}><Plus size={14}/>Add tag</button></div>
    {error && <p className="tag-picker-error">{error}</p>}
  </div>;
}
