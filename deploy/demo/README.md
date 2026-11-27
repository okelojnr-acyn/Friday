# The demo Friday

A sample shop anyone can try at https://demo.fridayhost.dev without
signing up: "Try as Owner" or "Try as Cashier". Everything works; the
whole business goes back to the same start every night. It's the
customer-server stack (../compose.yml) with this override, so it can run
on any machine; today it runs beside Friday Host on its box, whose Caddy
proxies demo.fridayhost.dev to it over the `friday-demo-edge` network.

Nothing reaches the outside world: no email or SMS settings, no payment
or KRA keys, and the kernel refuses connecting services, invites and Guss
in demo mode (`FRIDAY_DEMO_USERS`, kernel/internal/auth/demo.go).

    sudo sh setup.sh <release sha>      # once; secrets made on the box, never printed
    sudo /opt/friday-demo/seed.sh        # the sample shop, then golden.dump
    # every night at 00:00 Nairobi (21:00 UTC):
    echo '0 21 * * * root /opt/friday-demo/reset.sh >> /var/log/friday-demo-reset.log 2>&1' | sudo tee /etc/cron.d/friday-demo

Updating: run setup.sh with the new sha (keeps .env), then seed.sh again
on an empty database, or keep the old golden.dump if the schemas allow.
