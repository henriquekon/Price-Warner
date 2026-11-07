type Props = {
  page: number;
  pageSize: number;
  onPage: (value: number) => void;
  onPageSize: (value: number) => void;
  total?: number | null;
  hasNext?: boolean;
  disabled?: boolean;
};

export default function Pagination({page, pageSize, onPage, onPageSize, total, hasNext, disabled = false}: Props) {
  const pages = total == null ? null : Math.max(1, Math.ceil(total / pageSize));
  const nextAllowed = pages === null ? Boolean(hasNext) : page < pages;
  return <div className="pagination-bar" aria-label="Pagination controls">
    <div className="pagination-info">
      <span>{total == null ? `Page ${page}` : `${total} results · Page ${page} of ${pages}`}</span>
      <label>Per page
        <select aria-label="Items per page" disabled={disabled} value={pageSize} onChange={e => onPageSize(Number(e.target.value))}>
          {[10, 20, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}
        </select>
      </label>
    </div>
    <div className="pagination-actions">
      <button className="secondary" type="button" disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <button className="secondary" type="button" disabled={disabled || !nextAllowed} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  </div>;
}
