from decimal import Decimal
from sqlalchemy.orm import Session
from models import InvestmentHistory

def process_sell(session: Session, user_id: int, fund_id: int,
                 sell_date, sell_units: Decimal, sell_price: Decimal):
    """
    Process a SELL transaction using FIFO lots.
    - Inserts a SELL row
    - Consumes from oldest BUY lots
    - Updates units_remaining
    - Returns realized gain/loss
    """

    # Insert the SELL record itself
    sell_tx = InvestmentHistory(
        user_id=user_id,
        fund_id=fund_id,
        tx_date=sell_date,
        tx_type='SELL',
        units=sell_units,
        cost_per_unit=sell_price,
        total_cost=sell_units * sell_price,
        units_remaining=Decimal('0')
    )
    session.add(sell_tx)

    # FIFO consumption
    remaining_to_sell = sell_units
    realized_gain = Decimal('0')

    lots = (session.query(InvestmentHistory)
                  .filter_by(user_id=user_id, fund_id=fund_id, tx_type='BUY')
                  .filter(InvestmentHistory.units_remaining > 0)
                  .order_by(InvestmentHistory.tx_date.asc())
                  .with_for_update()  # lock rows for safety
                  .all())

    for lot in lots:
        if remaining_to_sell <= 0:
            break

        consume = min(lot.units_remaining, remaining_to_sell)
        lot.units_remaining -= consume
        remaining_to_sell -= consume

        # Gain/loss = (sell_price - buy_price) * units sold from this lot
        realized_gain += (sell_price - lot.cost_per_unit) * consume

    if remaining_to_sell > 0:
        raise ValueError("Not enough units to sell")

    session.commit()
    return realized_gain
