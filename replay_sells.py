def replay_sells(user_id: int, registrar: str = None):
    q = db.session.query(Investment).filter(
        Investment.user_id == user_id,
        Investment.units < 0
    )
    if registrar:
        q = q.filter(Investment.registrar == registrar)

    sells = q.order_by(Investment.date.asc()).all()

    for sell in sells:
        already_done = (db.session.query(InvestmentHistory)
                        .filter_by(user_id=sell.user_id,
                                   fund_id=sell.fund_id,
                                   tx_date=sell.date,
                                   tx_type='SELL',
                                   units=abs(sell.units))
                        .first())
        if already_done:
            continue

        try:
            process_sell(
                session=db.session,
                user_id=sell.user_id,
                fund_id=sell.fund_id,
                sell_date=sell.date,
                sell_units=abs(sell.units),
                sell_price=sell.nav
            )
        except ValueError as e:
            if "Not enough units" in str(e):
                # Defer until matching BUYs exist
                continue
            else:
                raise

    db.session.commit()
