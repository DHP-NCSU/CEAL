for l in 0.0 2.0
do
    for g in 0.0 2.0
    do
        python run/bbal.py --lambda_weight $l --gamma_weight $g &
        sleep 10
    done
done
