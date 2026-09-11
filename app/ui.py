"""Gradio UI for manually exercising the loan chatbot agent.

Mounted onto the main FastAPI app (see main.py's `gr.mount_gradio_app` call)
rather than run as a standalone Gradio server. `mount_gradio_app` wraps the
existing app's lifespan around Gradio's own, so everything - our
`mcp_client.start()`/`stop()` included - runs on the one uvicorn event loop
for the process's lifetime. A standalone `demo.launch()` would instead need
its own copy of that startup/shutdown lifecycle, and starting the MCP
client's stdio subprocess/anyio streams in one asyncio event loop and then
calling them from a different one breaks outright (a "bound to a different
event loop" error) - so mounting under the existing app isn't just less
code, it avoids that whole class of bug.

Each question is sent as an independent turn via `build_initial_messages`,
exactly like a real POST to /chat - this UI does not add multi-turn memory
that the actual API doesn't have; the visible chat history is a display-only
transcript, not agent state.

All UI-facing text (labels, suggested questions, loan type/status names) is
Mongolian per explicit user request - the underlying data (enum `.value`s,
field names) stays English, only the rendered labels are translated here.
"""

from uuid import UUID

import gradio as gr
from sqlalchemy import select

from app.agent.nodes import build_initial_messages, extract_text
from app.api.deps import get_agent
from app.database.models import Customer
from app.database.session import AsyncSessionLocal
from app.services import analytics_service, loan_service

SUGGESTED_QUESTIONS = [
    "Миний идэвхтэй зээлүүд юу вэ?",
    "Надад хугацаа хэтэрсэн төлбөр байна уу?",
    "Миний өр-орлогын харьцаа (DTI) хэд вэ?",
    "Миний зээлийн ерөнхий байдлыг хэлж өгөөч.",
    "Би хэдэн зээлтэй вэ?",
    "Миний сар бүрийн нийт төлбөр хэд вэ?",
]

LOAN_TYPE_LABELS_MN = {
    "mortgage": "Ипотек",
    "car": "Автомашины",
    "consumer": "Хэрэглээний",
    "business": "Бизнесийн",
    "credit_card": "Кредит картын",
}

LOAN_STATUS_LABELS_MN = {
    "active": "идэвхтэй",
    "overdue": "хугацаа хэтэрсэн",
    "closed": "хаагдсан",
}


async def _list_customers() -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as session:
        result = await session.scalars(select(Customer).order_by(Customer.full_name))
        customers = result.all()
    return [(customer.full_name, str(customer.id)) for customer in customers]


LOAN_TABLE_HEADERS = [
    "Төрөл",
    "Төлөв",
    "Үлдэгдэл (₮)",
    "Үндсэн дүн (₮)",
    "Сарын төлбөр (₮)",
    "Хүү (%)",
    "Эхэлсэн",
    "Дуусах",
]


async def _render_customer_info(customer_id: str | None) -> tuple[str, list[list]]:
    if not customer_id:
        return "_Зээлийн мэдээллийг харахын тулд харилцагч сонгоно уу._", []

    parsed_id = UUID(customer_id)
    async with AsyncSessionLocal() as session:
        profile = await loan_service.get_customer_profile(session, parsed_id)
        if profile is None:
            return "_Харилцагч олдсонгүй._", []
        loans = await loan_service.get_all_loans(session, parsed_id)
        dti = await analytics_service.calculate_dti(session, parsed_id)

    lines = [
        f"### {profile.full_name}",
        f"Сарын орлого: **{profile.monthly_income:,.0f} төгрөг**",
    ]
    if dti is not None:
        lines.append(f"Өр-орлогын харьцаа (DTI): **{dti.dti_ratio}%**")
    summary = "\n".join(lines)

    table = [
        [
            LOAN_TYPE_LABELS_MN.get(loan.loan_type.value, loan.loan_type.value),
            LOAN_STATUS_LABELS_MN.get(loan.status.value, loan.status.value),
            loan.remaining_balance,
            loan.principal_amount,
            loan.monthly_payment,
            loan.interest_rate,
            str(loan.start_date),
            str(loan.end_date),
        ]
        for loan in loans
    ]

    return summary, table


async def _respond(message: str, history: list[dict], customer_id: str | None) -> list[dict]:
    history = list(history)
    if not customer_id:
        history.append({"role": "assistant", "content": "Эхлээд харилцагч сонгоно уу."})
        return history
    if not message or not message.strip():
        return history

    agent = get_agent()
    result = await agent.ainvoke(
        {"customer_id": customer_id, "messages": build_initial_messages(message)}
    )
    reply = extract_text(result["messages"][-1].content)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return history


def _make_ask_handler(question: str):
    async def handler(history: list[dict], customer_id: str | None) -> list[dict]:
        return await _respond(question, history, customer_id)

    return handler


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Buren Loan Chatbot") as demo:
        gr.Markdown("# Зээлийн мэдээллийн чатбот")

        with gr.Row():
            with gr.Column(scale=1):
                chatbot = gr.Chatbot(label="Чат", height=520)
                with gr.Row():
                    textbox = gr.Textbox(
                        label="Асуулт",
                        placeholder="Зээлийн талаар асуугаарай...",
                        scale=4,
                        show_label=False,
                    )
                    send_btn = gr.Button("Илгээх", scale=1, variant="primary")

            with gr.Column(scale=1):
                customer_dropdown = gr.Dropdown(label="Харилцагч", choices=[])
                customer_info = gr.Markdown(
                    "_Зээлийн мэдээллийг харахын тулд харилцагч сонгоно уу._"
                )
                loan_table = gr.Dataframe(
                    headers=LOAN_TABLE_HEADERS,
                    datatype=["str", "str", "number", "number", "number", "number", "str", "str"],
                    row_count=0,
                    wrap=True,
                    interactive=False,
                )
                gr.Markdown("### Санал болгож буй асуултууд")
                question_buttons = [
                    gr.Button(question, size="sm") for question in SUGGESTED_QUESTIONS
                ]

        textbox.submit(
            fn=_respond, inputs=[textbox, chatbot, customer_dropdown], outputs=[chatbot]
        ).then(lambda: "", outputs=[textbox])
        send_btn.click(
            fn=_respond, inputs=[textbox, chatbot, customer_dropdown], outputs=[chatbot]
        ).then(lambda: "", outputs=[textbox])

        customer_dropdown.change(
            fn=_render_customer_info,
            inputs=[customer_dropdown],
            outputs=[customer_info, loan_table],
        )

        for question, button in zip(SUGGESTED_QUESTIONS, question_buttons):
            button.click(
                fn=_make_ask_handler(question),
                inputs=[chatbot, customer_dropdown],
                outputs=[chatbot],
            )

        async def _on_load():
            choices = await _list_customers()
            first_value = choices[0][1] if choices else None
            info, table = await _render_customer_info(first_value)
            return gr.update(choices=choices, value=first_value), info, table

        demo.load(fn=_on_load, outputs=[customer_dropdown, customer_info, loan_table])

    return demo
