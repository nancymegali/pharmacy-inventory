
import { useEffect, useState } from "react";
import {
  Activity, AlertTriangle, Boxes, Package,
  Search, RefreshCw, Pill, Plus, X, Pencil, Trash2
} from "lucide-react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

const formatPrice = (price) => {
  if (price === null || price === undefined || price === "") {
    return "—";
  }

  return Number(price).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};


const emptyForm = {
  name: "",
  strength: "",
  dosage_form: "",
  ndc: "",
  quantity: "0",
  reorder_level: "10",
  unit_price: "",
  expiration_date: "",
  supplier: "",
};

function App() {
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");


  const [medications, setMedications] = useState([]);
  const [search, setSearch] = useState("");
  const [activePage, setActivePage] = useState("medications");
  const [activeFilter, setActiveFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [movements, setMovements] = useState([]);
  const [showStockForm, setShowStockForm] = useState(false);
  const [stockForm, setStockForm] = useState({
    medication_id: "",
    movement_type: "received",
    quantity: "",
    reason: "",
  });
  const [stockError, setStockError] = useState("");
  const [stockSuccess, setStockSuccess] = useState("");
  const [stockLoading, setStockLoading] = useState(false);

  async function loadMedications() {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/medications`);
      if (!response.ok) throw new Error("Could not load inventory.");
      setMedications(await response.json());
    } catch {
      setError(
        "Unable to connect to the API. Make sure your FastAPI server is running."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMedications();
    fetchMovements();
  }, []);

  function handleEditMedication(med) {
    setEditingId(med.id);
    setShowAddForm(true);
    setFormError("");
    setFormSuccess("");

    setFormData({
      name: med.name ?? "",
      strength: med.strength ?? "",
      dosage_form: med.dosage_form ?? "",
      ndc: med.ndc ?? "",
      quantity: String(med.quantity ?? 0),
      reorder_level: String(med.reorder_level ?? 10),
      unit_price: med.unit_price == null ? "" : String(med.unit_price),
      expiration_date: med.expiration_date ?? "",
      supplier: med.supplier ?? "",
    });

    window.scrollTo({ top: 0, behavior: "smooth" });
  }


  async function handleDeleteMedication(med) {
    const confirmed = window.confirm(
      `Are you sure you want to delete ${med.name}? This cannot be undone.`
    );

    if (!confirmed) return;

    try {
      const response = await fetch(
        `${API_URL}/medications/${med.id}`,
        { method: "DELETE" }
      );

      if (!response.ok) {
        throw new Error("Could not delete medication.");
      }

      await loadMedications();
    } catch (err) {
      window.alert(err.message || "Unable to delete medication.");
    }
  }


  function handleFormChange(event) {
    const { name, value } = event.target;
    setFormData((previous) => ({ ...previous, [name]: value }));
  }

  
  async function handleAddMedication(event) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    setFormSuccess("");

    
    const payload = {
      name: formData.name.trim(),
      strength: formData.strength.trim(),
      dosage_form: formData.dosage_form,
      ndc: formData.ndc.trim() || null,
      quantity: Number(formData.quantity),
      reorder_level: Number(formData.reorder_level),
      unit_price:
        formData.unit_price === "" ? null : Number(formData.unit_price),
      expiration_date: formData.expiration_date || null,
      supplier: formData.supplier.trim() || null,
    };


    try {
      const isEditing = editingId !== null;

      const response = await fetch(
        isEditing
          ? `${API_URL}/medications/${editingId}`
          : `${API_URL}/medications`,
        {
          method: isEditing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "Could not save medication. Check the information and try again."
        );
      }

      await response.json();
      await loadMedications();

      setFormData({ ...emptyForm });
      setEditingId(null);
      setFormSuccess("");
      setFormError("");
      setShowAddForm(false);

    } catch (err) {
      setFormError(err.message || "Unable to save medication.");
    } finally {
      setSaving(false);
    }
  }


  const filtered = medications.filter((med) => {
    const matchesSearch = [med.name, med.ndc, med.supplier].some((value) =>
      value?.toLowerCase().includes(search.toLowerCase())
    );

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const expiry = med.expiration_date
      ? new Date(`${med.expiration_date}T00:00:00`)
      : null;

    const daysUntilExpiry = expiry
      ? (expiry - today) / (1000 * 60 * 60 * 24)
      : null;

    const isLowStock = med.quantity <= med.reorder_level;
    const isExpired = daysUntilExpiry !== null && daysUntilExpiry < 0;
    const isExpiringSoon =
      daysUntilExpiry !== null &&
      daysUntilExpiry >= 0 &&
      daysUntilExpiry <= 90;

    const matchesFilter =
      activeFilter === "all" ||
      (activeFilter === "low" && isLowStock) ||
      (activeFilter === "expiring" && isExpiringSoon) ||
      (activeFilter === "expired" && isExpired);

    return matchesSearch && matchesFilter;
  });

  const lowStock = medications.filter(
    (med) => med.quantity <= med.reorder_level
  ).length;

  const expiringSoon = medications.filter((med) => {
    if (!med.expiration_date) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const expiry = new Date(`${med.expiration_date}T00:00:00`);
    const days = (expiry - today) / (1000 * 60 * 60 * 24);
    return days >= 0 && days <= 90;
  }).length;

  
  const money = (value) =>
    value == null || value === ""
      ? "—"
      : Number(value).toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });


  const totalInventoryValue = medications.reduce(
    (total, med) =>
      total + (Number(med.quantity) * Number(med.unit_price ?? 0)),
    0
  );

  const fetchMovements = async () => {
    try {
      const response = await fetch(`${API_URL}/stock-movements`);

      if (!response.ok) {
        throw new Error("Could not load stock movement history.");
      }

      const data = await response.json();
      setMovements(data);
    } catch (error) {
      console.error("Error loading stock movements:", error);
    }
  };

  const handleStockSubmit = async (e) => {
    e.preventDefault();

    setStockError("");
    setStockSuccess("");
    setStockLoading(true);

    try {
      const response = await fetch(`${API_URL}/stock-movements`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          medication_id: Number(stockForm.medication_id),
          movement_type: stockForm.movement_type,
          quantity: Number(stockForm.quantity),
          reason: stockForm.reason.trim() || null,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "Could not record stock movement."
        );
      }

      setStockForm({
        medication_id: "",
        movement_type: "received",
        quantity: "",
        reason: "",
      });

      setStockError("");
      setStockSuccess("");
      setShowStockForm(false);

      await Promise.all([
        loadMedications(),
        fetchMovements(),
      ]);

    } catch (error) {
      setStockError(error.message);
    } finally {
      setStockLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon"><Pill size={23} /></div>
          <div>
            <strong>MedStock</strong>
            <span>INVENTORY SYSTEM</span>
          </div>
        </div>

        <p className="nav-label">WORKSPACE</p>
        <div
          className={`nav-item ${activePage === "medications" ? "active" : ""}`}
          onClick={() => setActivePage("medications")}
          role="button"
          tabIndex={0}
        >
          <Boxes size={18} /> Inventory
        </div>

        <div className="subnav">
          <button
            type="button"
            className={`subnav-item ${activePage === "medications" ? "selected" : ""}`}
            onClick={() => setActivePage("medications")}
          >
            <Pill size={16} />
            Medications
          </button>

          <button
            type="button"
            className={`subnav-item ${activePage === "history" ? "selected" : ""}`}
            onClick={() => {
              setActivePage("history");
              fetchMovements();
            }}
          >
            <Activity size={16} />
            Stock History
          </button>
        </div>
        <div className="sidebar-note">
          <Activity size={17} />
          <div><strong>System status</strong><span>Local development</span></div>
          <i />
        </div>
        <div className="sidebar-footer">
          PHARMACY INVENTORY<br />MANAGEMENT
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <span className="eyebrow">WORKSPACE / INVENTORY</span>
            <h1>Inventory overview</h1>
            <p>Monitor stock levels and keep your inventory organized.</p>
          </div>
          <div className="topbar-actions">
            <button
              type="button"
              className="refresh-button"
              onClick={loadMedications}
              disabled={loading}
            >
              <RefreshCw size={16} /> Refresh
            </button>

            <button
              type="button"
              className="refresh-button"
              onClick={() => {
                setStockForm({
                  medication_id: "",
                  movement_type: "received",
                  quantity: "",
                  reason: "",
                });
                setStockError("");
                setStockSuccess("");
                setShowStockForm(true);
              }}
            >
              <Plus size={17} /> Record stock
            </button>

            <button
              type="button"
              className="add-button"
              onClick={() => {
                setEditingId(null);
                setFormData({ ...emptyForm });
                setFormError("");
                setFormSuccess("");
                setShowAddForm(true);
              }}
            >
              <Plus size={17} /> Add medication
            </button>
          </div>
        </header>
        
        
      
        {/* ADD / EDIT MEDICATION POPUP */}
        {showAddForm && (
          <div
            className="modal-overlay"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                setShowAddForm(false);
                setEditingId(null);
                setFormData({ ...emptyForm });
                setFormError("");
                setFormSuccess("");
              }
            }}
          >
            <section
              className="modal-content"
              role="dialog"
              aria-modal="true"
              aria-labelledby="medication-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="modal-header">
                <div>
                  <h2 id="medication-modal-title">
                    {editingId !== null ? "Edit medication" : "Add medication"}
                  </h2>
                  <p>
                    {editingId !== null
                      ? "Update the medication details below."
                      : "Enter the details for a new inventory record."}
                  </p>
                </div>

                <button
                  type="button"
                  className="modal-close"
                  aria-label="Close medication form"
                  onClick={() => {
                    setShowAddForm(false);
                    setEditingId(null);
                    setFormData({ ...emptyForm });
                    setFormError("");
                    setFormSuccess("");
                  }}
                >
                  <X size={19} />
                </button>
              </div>

              <form onSubmit={handleAddMedication} className="medication-form">
                <label>
                  Medication name *
                  <input
                    name="name"
                    value={formData.name}
                    onChange={(event) =>
                      setFormData((previous) => ({
                        ...previous,
                        name: event.target.value.toUpperCase(),
                      }))
                    }
                    required
                    maxLength={150}
                    placeholder="e.g. AMOXICILLIN"
                  />
                </label>

                <label>
                  Strength *
                  <input
                    name="strength"
                    value={formData.strength}
                    onChange={(event) =>
                      setFormData((previous) => ({
                        ...previous,
                        strength: event.target.value.toUpperCase(),
                      }))
                    }
                    required
                    maxLength={50}
                    placeholder="e.g. 500 MG"
                  />
                </label>

                <label>
                  Dosage form *
                  <select
                    name="dosage_form"
                    value={formData.dosage_form}
                    onChange={handleFormChange}
                    required
                  >
                    <option value="">Select dosage form</option>
                    <option value="Tablet">TABLET</option>
                    <option value="Capsule">CAPSULE</option>
                    <option value="Oral solution">ORAL SOLUTION</option>
                    <option value="Suspension">SUSPENSION</option>
                    <option value="Cream">CREAM</option>
                    <option value="Ointment">OINTMENT</option>
                    <option value="Gel">GEL</option>
                    <option value="Lotion">LOTION</option>
                    <option value="Drops">DROPS</option>
                    <option value="Inhaler">INHALER</option>
                    <option value="Injection">INJECTION</option>
                    <option value="Patch">PATCH</option>
                    <option value="Suppository">SUPPOSITORY</option>
                    <option value="Powder">POWDER</option>
                    <option value="Other">OTHER</option>
                  </select>
                </label>

                <label>
                  NDC *
                  <input
                    name="ndc"
                    value={formData.ndc}
                    onChange={(event) => {
                      const digits = event.target.value.replace(/\D/g, "").slice(0, 11);

                      let formatted = digits;
                      if (digits.length > 5) {
                        formatted = `${digits.slice(0, 5)}-${digits.slice(5)}`;
                      }
                      if (digits.length > 9) {
                        formatted = `${digits.slice(0, 5)}-${digits.slice(5, 9)}-${digits.slice(9)}`;
                      }

                      setFormData((previous) => ({
                        ...previous,
                        ndc: formatted,
                      }));
                    }}
                    placeholder="12345-6789-01"
                    maxLength={13}
                    pattern="[0-9]{5}-[0-9]{4}-[0-9]{2}"
                    title="Enter NDC in the format 12345-6789-01"
                    required
                  />
                </label>

                <label>
                  Quantity in stock *
                  <input
                    type="number"
                    name="quantity"
                    value={formData.quantity}
                    onChange={handleFormChange}
                    min="0"
                    step="1"
                    required
                  />
                </label>

                <label>
                  Reorder level *
                  <input
                    type="number"
                    name="reorder_level"
                    value={formData.reorder_level}
                    onChange={handleFormChange}
                    min="0"
                    step="1"
                    required
                  />
                </label>
   
                <label>
                  Unit price ($)
                  <input
                    type="number"
                    name="unit_price"
                    value={formData.unit_price}
                    onChange={handleFormChange}
                    min="0"
                    step="0.01"
                    placeholder="Optional"
                  />
                </label>

                <label>
                  Expiration date
                  <input
                    type="date"
                    name="expiration_date"
                    value={formData.expiration_date}
                    onChange={handleFormChange}
                  />
                </label>

                <label className="full-width-field">
                  Supplier
                  <input
                    name="supplier"
                    value={formData.supplier}
                    onChange={handleFormChange}
                    maxLength={150}
                    placeholder="Optional"
                  />
                </label>

                {formError && (
                  <p className="form-message form-error">{formError}</p>
                )}

                <div className="form-actions">
                  <button
                    type="button"
                    className="refresh-button"
                    onClick={() => {
                      setShowAddForm(false);
                      setEditingId(null);
                      setFormData({ ...emptyForm });
                      setFormError("");
                      setFormSuccess("");
                    }}
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="add-button"
                    disabled={saving}
                  >
                    {saving
                      ? "Saving..."
                      : editingId !== null
                        ? "Save changes"
                        : "Save medication"}
                  </button>
                </div>
              </form>
            </section>
          </div>
        )}

        {/* RECORD STOCK POPUP */}
        {showStockForm && (
          <div
            className="modal-overlay"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                setShowStockForm(false);
                setStockError("");
                setStockSuccess("");
              }
            }}
          >
            <section
              className="modal-content modal-stock"
              role="dialog"
              aria-modal="true"
              aria-labelledby="stock-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="modal-header">
                <div>
                  <h2 id="stock-modal-title">Record stock movement</h2>
                  <p>Record a delivery, removal, or stock correction.</p>
                </div>

                <button
                  type="button"
                  className="modal-close"
                  aria-label="Close stock form"
                  onClick={() => {
                    setShowStockForm(false);
                    setStockError("");
                    setStockSuccess("");
                  }}
                >
                  <X size={19} />
                </button>
              </div>

              <form onSubmit={handleStockSubmit} className="medication-form">
                <label>
                  Medication *
                  <select
                    value={stockForm.medication_id}
                    onChange={(event) =>
                      setStockForm((previous) => ({
                        ...previous,
                        medication_id: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="">Select a medication</option>
                    {medications.map((med) => (
                      <option key={med.id} value={med.id}>
                        {med.name} (Current stock: {med.quantity})
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Movement type *
                  <select
                    value={stockForm.movement_type}
                    onChange={(event) =>
                      setStockForm((previous) => ({
                        ...previous,
                        movement_type: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="received">Receive stock</option>
                    <option value="removed">Remove stock</option>
                    <option value="adjustment">Adjust to actual quantity</option>
                  </select>
                </label>

                <label>
                  {stockForm.movement_type === "adjustment"
                    ? "New total quantity *"
                    : "Quantity *"}
                  <input
                    type="number"
                    min={stockForm.movement_type === "adjustment" ? "0" : "1"}
                    step="1"
                    value={stockForm.quantity}
                    onChange={(event) =>
                      setStockForm((previous) => ({
                        ...previous,
                        quantity: event.target.value,
                      }))
                    }
                    required
                  />
                </label>

                <label>
                  Reason
                  <input
                    type="text"
                    maxLength={255}
                    placeholder="e.g. Demo delivery"
                    value={stockForm.reason}
                    onChange={(event) =>
                      setStockForm((previous) => ({
                        ...previous,
                        reason: event.target.value,
                      }))
                    }
                  />
                </label>

                {stockError && (
                  <p className="form-message form-error">{stockError}</p>
                )}

                <div className="form-actions">
                  <button
                    type="button"
                    className="refresh-button"
                    onClick={() => {
                      setShowStockForm(false);
                      setStockError("");
                      setStockSuccess("");
                    }}
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="add-button"
                    disabled={stockLoading || medications.length === 0}
                  >
                    {stockLoading ? "Recording..." : "Save stock movement"}
                  </button>
                </div>
              </form>
            </section>
          </div>
        )}

        {activePage === "medications" && (
        <>

          <section className="stats-grid">
            <button
              type="button"
              className={`stat-card ${activeFilter === "all" ? "selected" : ""}`}
              onClick={() => setActiveFilter("all")}
              aria-pressed={activeFilter === "all"}
            >
              <div className="stat-top">
                <span>Total medications</span>
                <Package />
              </div>
              <strong>{medications.length}</strong>
              <small>Inventory records · Click to show all</small>
            </button>

            <button
              type="button"
              className={`stat-card ${activeFilter === "all" ? "" : ""}`}
              onClick={() => setActiveFilter("all")}
            >
              <div className="stat-top">
                <span>Units in stock</span>
                <Boxes />
              </div>
              <strong>
                {medications.reduce((sum, med) => sum + med.quantity, 0).toLocaleString()}
              </strong>
              <small>Across all records</small>
            </button>

            <button
              type="button"
              className={`stat-card ${activeFilter === "low" ? "selected" : ""}`}
              onClick={() => setActiveFilter(activeFilter === "low" ? "all" : "low")}
              aria-pressed={activeFilter === "low"}
            >
              <div className="stat-top">
                <span>Low stock</span>
                <AlertTriangle />
              </div>
              <strong>{lowStock}</strong>
              <small>Click to filter inventory</small>
            </button>

            <button
              type="button"
              className={`stat-card ${activeFilter === "expiring" ? "selected" : ""}`}
              onClick={() =>
                setActiveFilter(activeFilter === "expiring" ? "all" : "expiring")
              }
              aria-pressed={activeFilter === "expiring"}
            >
              <div className="stat-top">
                <span>Expiring soon</span>
                <Activity />
              </div>
              <strong>{expiringSoon}</strong>
              <small>Within the next 90 days</small>
            </button>

            <button
              type="button"
              className="stat-card"
              style={{ cursor: "default" }}
            >
              <div className="stat-top">
                <span>Total inventory value</span>
                <Package />
              </div>
              <strong>
                {totalInventoryValue.toLocaleString("en-US", {
                  style: "currency",
                  currency: "USD",
                })}
              </strong>
              <small>Based on recorded unit prices</small>
            </button>

          </section>


        <section className="inventory-panel">
          <div className="panel-heading">
            <div>
              <h2>Medication inventory</h2>
              <p>Search and review your current stock.</p>
            </div>
            <span className="record-count">{filtered.length} records</span>
          </div>

          <div className="toolbar">
            <div className="search-box">
              <Search size={18} />
              <input
                placeholder="Search medication, NDC, or supplier..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </div>

          {error && <div className="error-message">{error}</div>}

          {loading ? (
            <div className="empty-state">Loading inventory...</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Medication</th>
                    <th>NDC</th>
                    <th>In stock</th>
                    <th>Reorder at</th>
                    <th>Unit price</th>
                    <th>Expiration</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((med) => {
                    const low = med.quantity <= med.reorder_level;
                    const expired = med.expiration_date &&
                      new Date(`${med.expiration_date}T00:00:00`) <
                      new Date(new Date().toDateString());

                    return (
                      <tr key={med.id}>
                        <td>
                          <div className="med-name">
                            <span className="med-icon"><Pill size={16} /></span>
                            <strong>{med.name}</strong>
                          </div>
                        </td>
                        <td className="muted">{med.ndc || "—"}</td>
                        <td><strong>{med.quantity}</strong></td>
                        <td>{med.reorder_level}</td>
                        <td>{money(med.unit_price)}</td>
                        <td>{med.expiration_date || "—"}</td>
                        <td>
                          {expired
                            ? <span className="status expired">Expired</span>
                            : low
                              ? <span className="status low">Low stock</span>
                              : <span className="status good">In stock</span>}
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              type="button"
                              className="edit-button"
                              onClick={() => handleEditMedication(med)}
                            >
                              <Pencil size={14} />
                              Edit
                            </button>

                            <button
                              type="button"
                              className="delete-button"
                              onClick={() => handleDeleteMedication(med)}
                              aria-label={`Delete ${med.name}`}
                              title="Delete medication"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan="8" className="empty-state">
                        No matching medications found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          <div className="panel-footer">
            <span>Inventory data from your local MySQL database</span>
            <span><i className="online-dot" /> API connection</span>
          </div>
        </section>

        </>
        )}
        {activePage === "history" && (
          <section className="inventory-panel">
            <div className="panel-heading">
              <div>
                <h2>Stock movement history</h2>
                <p>Review previously recorded inventory changes.</p>
              </div>

              <button
                type="button"
                className="refresh-button"
                onClick={fetchMovements}
              >
                <RefreshCw size={16} /> Refresh history
              </button>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Medication</th>
                    <th>Movement</th>
                    <th>Quantity change</th>
                    <th>Reason</th>
                  </tr>
                </thead>

                <tbody>
                  {movements.map((movement) => (
                    <tr key={movement.id}>
                      <td>
                        {movement.created_at
                          ? new Date(movement.created_at).toLocaleString()
                          : "—"}
                      </td>
                      <td>
                        <strong>{movement.medication_name}</strong>
                      </td>
                      <td>
                        {movement.movement_type === "received"
                          ? "Received"
                          : movement.movement_type === "removed"
                            ? "Removed"
                            : "Adjustment"}
                      </td>
                      <td>
                        <strong>
                          {movement.quantity_change > 0 ? "+" : ""}
                          {movement.quantity_change}
                        </strong>
                      </td>
                      <td>{movement.reason || "—"}</td>
                    </tr>
                  ))}

                  {movements.length === 0 && (
                    <tr>
                      <td colSpan="5" className="empty-state">
                        No stock movements recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}


        <footer className="page-footer">
          MedStock · Pharmacy Inventory Management
        </footer>
      </main>
    </div>
  );
}

export default App;
