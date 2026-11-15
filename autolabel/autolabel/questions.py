"""The two labeling questions, asked in one request per complaint.

Wording was written on the dev split with both models in the loop, then frozen before the tune and held-out runs.
The instructions are the same for every backend. Whether options carry a one-line description is set per backend
(deciders.Backend.describe_options), to what did best for that model on dev: descriptions helped Jev on the issue
question (65.5% vs 60.0% accuracy) and hurt Strands Decider (53.6% vs 64.5%)."""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# The complaint database's 11 product categories (2025), with a one-line description of what each covers.
PRODUCTS = {
    "Credit reporting or other personal consumer reports":
        "Credit reports and credit scores, and the agencies that compile them: wrong or unknown accounts on a report, "
        "disputes, identity theft on a report, hard inquiries, background or tenant screening reports",
    "Debt collection":
        "A collector, collection agency or creditor trying to collect a debt: calls, letters, validation, "
        "debts the consumer says they don't owe, threats of legal action",
    "Money transfer, virtual currency, or money service":
        "Sending or receiving money: payment apps, mobile wallets, wire transfers, cryptocurrency exchanges, "
        "money orders, check cashing",
    "Checking or savings account":
        "A bank or credit union checking or savings account: deposits, withdrawals, holds, overdraft fees, "
        "opening or closing the account, debit card transactions on the account",
    "Credit card":
        "A credit card account: purchases and charges, disputes, fees and interest, applying for a card, "
        "rewards and promotions, closing the card",
    "Mortgage":
        "A home loan: payments, escrow, servicing, modification, foreclosure, applying for or closing on a mortgage",
    "Vehicle loan or lease":
        "A car or other vehicle loan or lease: payments, repossession, payoff, getting the loan or lease",
    "Student loan":
        "A federal or private student loan: servicing, repayment plans, forgiveness, deferment",
    "Payday loan, title loan, personal loan, or advance loan":
        "A payday loan, vehicle title loan, installment or personal loan, line of credit, or cash advance app",
    "Prepaid card":
        "A prepaid or reloadable card, gift card, or government benefits card",
    "Debt or credit management":
        "A debt settlement, debt relief, credit repair or credit counseling service",
}

CONTEXT = ("A complaint a consumer submitted to a US government agency about a financial product or service. "
           "Personal details such as names, account numbers and dates are redacted as XXXX.")


def taxonomy() -> dict:
    """{product: {issue: description}}, written by `autolabel build-data` from the database's own labels."""
    return json.loads((DATA / "taxonomy.json").read_text())


def state(text: str) -> dict:
    return {"context": CONTEXT, "complaint": text}


def questions(product: str, issues: dict, describe_options: bool = True) -> dict:
    """`product` picks which issue list to offer: the true product when measuring the issue task on its own,
    the predicted product when labeling new data. Without `describe_options` the options are bare labels."""
    def options(d: dict) -> dict:
        return d if describe_options else {k: None for k in d}
    return {
        "product": {
            "type": "choice",
            "instructions": "Which financial product or service is `complaint` about?",
            "criteria": options(PRODUCTS),
        },
        "issue": {
            "type": "choice",
            "instructions": f"`complaint` is about this product: {product}. "
                            "What is the main problem the consumer describes?",
            "criteria": options(issues[product]),
        },
    }
