import os
from urllib.parse import urljoin
import discord
import dotenv
import pymysql
import requests

dotenv.load_dotenv()

bot = discord.Bot()


errmap = {
    "USER_NOT_FOUND": "해당 사용자가 존재하지 않습니다.",
    "NOT_A_PERSONAL_BALANCE": "해당 잔고는 개인잔고가 아닙니다.",
    "BOOTH_BALANCE_NOT_FOUND": "해당 부스 잔고가 존재하지 않습니다.",
    "NOT_A_BOOTH_OPERATIONAL_BALANCE": "해당 잔고는 부스 잔고가 아닙니다.",
    "PAYMENT_RECORD_NOT_FOUND": "해당 결제내역이 존재하지 않습니다.",
    "PAYMENT_ALREADY_CANCELLED": "이미 결제가 취소되었습니다.",
    "PAYMENT_CANCELLATION_STATUS_NOT_UPDATED": "결제 취소 상태를 업데이트하지 못했습니다.",
    "SENDER_ID_EQUALS_RECEIVER_ID": "송금자와 수신자가 일치합니다.",
    "INVALID_TRANSFER_AMOUNT": "송금액이 올바른지 확인하십시오.",
    "INVALID_SENDER_ID": "송금자ID가 잘못되었습니다.",
    "INSUFFICIENT_SENDER_BALANCE": "송금자의 잔액이 부족합니다.",
    "INVALID_RECEIVER_ID": "수신자ID가 잘못되었습니다.",
    "SENDER_BALANCE_NOT_UPDATED": "송금자 금액을 업데이트하지 못했습니다.",
    "RECEIVER_BALANCE_NOT_UPDATED": "수신자 금액을 업데이트하지 못했습니다.",
    "NOT_ALLOWED": "허용되지 않은 사용자가 환전을 시도했습니다.",
    "BOOTH_NOT_FOUND": "부스가 존재하지 않음",
    "PAYMENT_NOT_FOUND": "결제정보가 존재하지 않음",
    "BOOTH_BALANCE_NOT_FOUND": "부스 잔고가 존재하지 않습니다.",
}


def balance_charge(user_id: int, amount: int, message: str = None):
    res = requests.post(
        urljoin(os.environ["HANUM_PAYMENT_BACKEND_URL"], "/eoullim/exchange/transfer"),
        json={
            "userId": user_id,
            "amount": amount,
            "message": message[:24] if message else None,
        },
        headers={
            "Authorization": f"Bearer {os.environ['HANUM_PAYMENT_BACKEND_TOKEN']}",
        },
    )

    try:
        data = res.json()
    except Exception:
        data = res.text

    return res.ok, data


class Connection:
    def __init__(self):
        self.conn = pymysql.connect(
            host=os.environ["HANUM_DB_HOST"],
            port=int(os.environ["HANUM_DB_PORT"]),
            user=os.environ["HANUM_DB_USER"],
            password=os.environ["HANUM_DB_PASSWORD"],
            db=os.environ["HANUM_DB_DATABASE"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def __enter__(self):
        return self.conn.cursor()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.commit()
        self.conn.close()


HANUM_PAYMENT_ADMINS = [int(i.strip()) for i in os.environ["HANUM_PAYMENT_ADMINS"].split(",")]


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")


def get_user(user_id: int):
    with Connection() as cursor:
        cursor.execute("SELECT id, name, phone FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

    return user


async def _잔고충전_user_autocomplete(ctx: discord.AutocompleteContext):
    user = ctx.options.get("user", "")
    print(user)
    with Connection() as cursor:
        cursor.execute(
            "SELECT id, name, phone FROM users WHERE name LIKE %s OR phone LIKE %s",
            (f"%{user}%", f"%{user}%"),
        )
        users = cursor.fetchall()

    return [f"{user['name']} ({user['phone'][-4:]}):{user['id']}" for user in users]


class 충전Modal(discord.ui.Modal):
    def __init__(self, user_id: int):
        super().__init__(title="충전 확인")
        self.user_id = user_id
        self.add_item(
            discord.ui.InputText(
                label=f"충전금액",
                placeholder="금액을 입력해주세요. (500원 ~ 50,000원)",
                min_length=3,
                max_length=5,
                required=True,
            )
        )
        self.add_item(
            discord.ui.InputText(
                label=f"충전메시지", placeholder="충전메시지를 입력해주세요. (최대 24자)", max_length=24, required=False
            )
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            amount = int(self.children[0].value)
            message = self.children[1].value

            if amount < 500 or amount > 50000:
                await interaction.response.send_message("충전금액은 500원 ~ 50,000원 사이여야 합니다.", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message("잘못된 입력입니다.", ephemeral=True)
            return

        succ, res = balance_charge(
            self.user_id,
            amount,
            message,
        )

        if not succ:
            if isinstance(res, dict):
                res = res["message"]
                res = errmap.get(res, res)

            await interaction.response.send_message(f"충전에 실패했습니다. ({res})", ephemeral=True)
            return

        data = res["data"]
        user_info = get_user(self.user_id)

        embed = discord.Embed(
            title="충전 완료",
            fields=[
                discord.EmbedField("시스템유동금", f"{data['totalExchangeAmount']:,}원", True),
                discord.EmbedField("충전금액", f"{data['transaction']['transferAmount']:,}원", True),
                discord.EmbedField(
                    "충전자", f"{self.user_id} {user_info['name']} ({user_info['phone'][-4:]})", True
                ),
                discord.EmbedField("트랜잭션고유번호", data["transaction"]["id"], True),
                discord.EmbedField("충전메시지", data["transaction"]["message"] or "", True),
                discord.EmbedField("충전시간", data["transaction"]["time"], True),
            ],
        )

        await interaction.response.send_message(embed=embed)


@bot.slash_command(guild_ids=[os.environ["HANUM_DISCORD_GUILD_ID"]])
@discord.option(
    "user",
    type=str,
    description="충전할 유저를 선택해주세요.",
    required=True,
    autocomplete=discord.utils.basic_autocomplete(
        _잔고충전_user_autocomplete,
    ),
)
async def 잔고충전(
    ctx: discord.ApplicationContext,
    user: str,
):
    if not user:
        await ctx.respond("잘못된 입력입니다.", ephemeral=True)
        return

    if ctx.author.id not in HANUM_PAYMENT_ADMINS:
        await ctx.respond("권한이 없습니다.", ephemeral=True)
        return

    try:
        user_id = int(user.split(":")[1])
    except Exception:
        await ctx.respond("잘못된 유저입니다.", ephemeral=True)
        return

    await ctx.send_modal(충전Modal(user_id))


bot.run(os.environ["HANUM_DISCORD_TOKEN"])
