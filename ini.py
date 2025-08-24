from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

DB_PATH = Path(__file__).resolve().parent.parent / "finance.db"

ExpenseOrIncome = Literal["expense", "income"]

EXPENSE_CATEGORIES = [
    "Alimentação", "Moradia", "Transporte", "Saúde", "Educação",
    "Lazer", "Vestuário", "Impostos", "Assinaturas", "Pets",
    "Doações", "Outros"
]
INCOME_CATEGORIES = [
    "Salário", "Vendas", "Investimentos", "Presente", "Reembolso", "Outros"
]
PAYMENT_METHODS = ["pix", "débito", "crédito", "dinheiro", "boleto", "transferência"]

# ----------------------------- MODELO ---------------------------------

@dataclass
class Transaction:
    kind: ExpenseOrIncome
    date_iso: str               # YYYY-MM-DD
    amount_cents: int           # armazenar em centavos evita erros de float
    category: str
    description: str = ""
    account: str = "principal"
    payment_method: str = "pix"
    tags: Optional[str] = None  # "tag1,tag2"

# -------------------------- BANCO DE DADOS ----------------------------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL CHECK(type IN ('income','expense')),
              date TEXT NOT NULL,  -- ISO yyyy-mm-dd
              amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
              category TEXT NOT NULL,
              description TEXT,
              account TEXT DEFAULT 'principal',
              payment_method TEXT DEFAULT 'pix',
              tags TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
            CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);
            CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);
            """
        )

# ----------------------------- VALIDAÇÃO ------------------------------

def normalize_date_to_iso(date_str: str) -> str:
    """
    Aceita 'YYYY-MM-DD' ou 'DD/MM/YYYY' e normaliza pra 'YYYY-MM-DD'.
    """
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Data inválida. Use YYYY-MM-DD ou DD/MM/YYYY.")

def parse_amount_to_cents(value_str: str) -> int:
    """
    Converte '1.234,56' ou '1234.56' ou '1234' -> centavos (int).
    Regras:
      - se tem '.' e ',' -> assume pt-BR ('.' milhar, ',' decimal)
      - se tem só ','   -> vírgula é decimal
      - se tem só '.'   -> ponto é decimal
      - senão           -> inteiro em reais
    """
    s = value_str.strip().replace("R$", "").replace(" ", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    # elif "." in s:  # já está no formato decimal com ponto
    # else:           # inteiro
    try:
        valor = float(s)
    except ValueError:
        raise ValueError("Valor inválido. Exemplos válidos: 123,45 | 123.45 | 1234")
    if valor <= 0:
        raise ValueError("Valor deve ser maior que zero.")
    cents = round(valor * 100)
    return int(cents)

def validate_category(kind: ExpenseOrIncome, category: str) -> str:
    allowed = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    cat = category.strip() or "Outros"
    # Mantemos o que o usuário digitar, mas alertamos se não está na lista
    if cat not in allowed:
        print(f"[aviso] Categoria '{cat}' não está na lista padrão. "
              f"Considere uma destas: {', '.join(allowed)}")
    return cat

def validate_payment_method(method: str) -> str:
    m = method.strip().lower()
    if m and m not in PAYMENT_METHODS:
        print(f"[aviso] Método '{m}' não está na lista padrão. "
              f"Use: {', '.join(PAYMENT_METHODS)}")
    return m or "pix"

# --------------------------- PERSISTÊNCIA -----------------------------

def is_duplicate(tx: Transaction) -> bool:
    """
    Define duplicata como mesma (type, date, amount_cents, category, description).
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT COUNT(1) FROM transactions
             WHERE type=? AND date=? AND amount_cents=? AND category=? AND IFNULL(description,'')=?
            """,
            (tx.kind, tx.date_iso, tx.amount_cents, tx.category, tx.description or "")
        )
        return cur.fetchone()[0] > 0

def save_transaction(tx: Transaction, allow_duplicate: bool = False) -> int:
    if (not allow_duplicate) and is_duplicate(tx):
        raise ValueError("Transação já existe (possível duplicata).")
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions
            (type, date, amount_cents, category, description, account, payment_method, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx.kind, tx.date_iso, tx.amount_cents, tx.category, tx.description,
                tx.account, tx.payment_method, tx.tags, now, now
            )
        )
        return cur.lastrowid

# --------------------------- API DE ALTO NÍVEL ------------------------

def add_expense(
    date_str: str,
    amount_str: str,
    category: str,
    description: str = "",
    account: str = "principal",
    payment_method: str = "pix",
    tags: Optional[str] = None,
    allow_duplicate: bool = False,
) -> int:
    date_iso = normalize_date_to_iso(date_str)
    cents = parse_amount_to_cents(amount_str)
    cat = validate_category("expense", category)
    method = validate_payment_method(payment_method)
    tx = Transaction(
        kind="expense",
        date_iso=date_iso,
        amount_cents=cents,
        category=cat,
        description=description.strip(),
        account=account.strip() or "principal",
        payment_method=method,
        tags=tags,
    )
    return save_transaction(tx, allow_duplicate=allow_duplicate)

def add_income(
    date_str: str,
    amount_str: str,
    category: str,
    description: str = "",
    account: str = "principal",
    payment_method: str = "pix",
    tags: Optional[str] = None,
    allow_duplicate: bool = False,
) -> int:
    date_iso = normalize_date_to_iso(date_str)
    cents = parse_amount_to_cents(amount_str)
    cat = validate_category("income", category)
    method = validate_payment_method(payment_method)
    tx = Transaction(
        kind="income",
        date_iso=date_iso,
        amount_cents=cents,
        category=cat,
        description=description.strip(),
        account=account.strip() or "principal",
        payment_method=method,
        tags=tags,
    )
    return save_transaction(tx, allow_duplicate=allow_duplicate)

# ----------------------------- UTILIDADES -----------------------------

def cents_to_brl(cents: int) -> str:
    valor = cents / 100.0
    # Formata em pt-BR sem depender de locale
    inteiro, frac = f"{valor:.2f}".split(".")
    inteiro_com_pontos = "".join(reversed([ "".join(reversed(inteiro))[i:i+3] for i in range(0, len(inteiro), 3) ]))
    inteiro_com_pontos = ".".join([inteiro[max(i-3,0):i] for i in range(len(inteiro), 0, -3)][::-1]) or "0"
    return f"R$ {inteiro_com_pontos},{frac}"

def list_last(n: int = 10):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id, type, date, amount_cents, category, IFNULL(description,''), account, payment_method "
            "FROM transactions ORDER BY date DESC, id DESC LIMIT ?", (n,)
        )
        rows = cur.fetchall()
    print("\nÚltimas transações:")
    for r in rows:
        id_, kind, date_iso, cents, cat, desc, acc, pm = r
        sinal = "-" if kind == "expense" else "+"
        print(f"#{id_:04d} [{date_iso}] {sinal}{cents_to_brl(cents)} | {kind} | {cat} | {desc} | {acc}/{pm}")
    if not rows:
        print("(vazio)")

# ------------------------------- CLI ----------------------------------

def cli_loop():
    print("=== Controle Financeiro (CLI) ===")
    print("Dicas de formatos:")
    print("- Data: YYYY-MM-DD ou DD/MM/YYYY")
    print("- Valor: 1.234,56  ou  1234.56  ou  1234\n")

    while True:
        print("\n[1] Adicionar DESPESA")
        print("[2] Adicionar RECEITA")
        print("[3] Listar últimas 10")
        print("[0] Sair")
        op = input("Escolha: ").strip()
        if op == "0":
            break
        elif op == "1":
            try:
                date = input("Data: ")
                amount = input("Valor (R$): ")
                category = input(f"Categoria (ex: {', '.join(EXPENSE_CATEGORIES[:5])}, ...): ")
                desc = input("Descrição (opcional): ")
                acc = input("Conta (padrão 'principal'): ") or "principal"
                pm = input(f"Método (ex: {', '.join(PAYMENT_METHODS)}): ") or "pix"
                tx_id = add_expense(date, amount, category, desc, acc, pm)
                print(f"OK! Despesa registrada com id #{tx_id}.")
            except Exception as e:
                print(f"ERRO: {e}")
        elif op == "2":
            try:
                date = input("Data: ")
                amount = input("Valor (R$): ")
                category = input(f"Categoria (ex: {', '.join(INCOME_CATEGORIES[:5])}, ...): ")
                desc = input("Descrição (opcional): ")
                acc = input("Conta (padrão 'principal'): ") or "principal"
                pm = input(f"Método (ex: {', '.join(PAYMENT_METHODS)}): ") or "pix"
                tx_id = add_income(date, amount, category, desc, acc, pm)
                print(f"OK! Receita registrada com id #{tx_id}.")
            except Exception as e:
                print(f"ERRO: {e}")
        elif op == "3":
            list_last(10)
        else:
            print("Opção inválida.")

if __name__ == "__main__":
    init_db()
    cli_loop()